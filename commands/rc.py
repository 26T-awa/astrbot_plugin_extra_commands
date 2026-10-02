"""/rc：概率回复开关（每个会话各自一份）。

原理：给每个开启的会话各注册一条 basic 定时任务，每 3 小时跑一次
`scripts/roll_ask.py` 掷骰——
- 未命中（MISS）：本轮直接结束，连一次 LLM 调用都没有；
- 命中（HIT）：用该会话的模型生成一个问题并发送。
开关状态按会话（unified_msg_origin）存在 `randomchat_state.json` 的 `sessions` 里，
定时任务的 payload 也带上同一个 umo；某个会话关掉之后，它的任务不再掷骰，
完全安静，也不影响别的会话。
"""

import asyncio
import random
import sys
from datetime import datetime, timezone
from functools import partial
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult
from astrbot.api.message_components import Plain

from ..core import cron, storage, timeutil
from ..core.args import parse_args
from ..core.exceptions import ArgsInputError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level

ORIGIN = "randomchat"  # 写在定时任务 payload 里的来源标记
JOB_NAME = "概率回复（脚本掷骰）"
CRON = "0 */3 * * *"  # 每 3 小时让脚本掷一次骰子
TIMEZONE = "Asia/Shanghai"
SCRIPT = storage.PLUGIN_ROOT / "scripts" / "roll_ask.py"  # 掷骰脚本：命中打 HIT 退 0，未命中打 MISS 退 1
SCRIPT_NAME = SCRIPT.name  # 聊天文案里只用文件名，不暴露完整路径
SCRIPT_TIMEOUT = 30  # 单次脚本运行的超时秒数
LLM_TIMEOUT = 45  # 命中后生成问题的超时秒数
STATE_FILE = storage.PLUGIN_DATA_DIR / "randomchat_state.json"
MAX_SESSIONS = 20  # 同时开启概率回复的会话数上限，避免定时任务无限增长
MAX_LIST = 10  # /rc list 最多列出的会话数
SYSTEM_PROMPT = (
    "你在和一个熟悉的人聊天，现在主动问他一个问题。"
    "一句话，自然、具体，不要堆砌表情符号，也不要提到任何机制或定时任务。"
)
FALLBACKS = (
    "今天有没有遇到什么让你想吐槽的事情？",
    "最近有没有在认真做一件事？说来听听。",
    "如果现在可以瞬移到任意一个地方，你会去哪里？",
    "你上一次觉得「啊，这个挺有意思」是什么时候？",
)


async def setup(plugin) -> None:
    """插件启动时调用：迁移旧状态，并把每个开着概率回复的会话重新调度起来。"""
    try:
        _migrate_legacy()
    except Exception as e:  # noqa: BLE001 - 迁移失败不能拖垮插件加载
        logger.error(f"迁移概率回复状态失败：{e}")

    try:
        await _reconcile_jobs(plugin)  # 先把库里用不上的任务停掉
    except Exception as e:  # noqa: BLE001 - 清理失败不影响正常恢复
        logger.error(f"清理概率回复任务失败：{e}")

    opened = list(_enabled_sessions())
    if len(opened) > MAX_SESSIONS:
        logger.warning(f"开着的会话有 {len(opened)} 个，超过上限 {MAX_SESSIONS}，只恢复前 {MAX_SESSIONS} 个")
        opened = opened[:MAX_SESSIONS]

    for umo in opened:
        try:
            await _ensure_job(plugin, umo, enabled=True)
        except Exception as e:  # noqa: BLE001 - 单个会话出问题不影响其他会话
            logger.error(f"恢复会话 {umo} 的概率回复任务失败：{e}")


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """开关概率回复：/rc on|off|status|list（需 admin）。"""
    ensure_level(event, Level.ADMIN)
    args = parse_args(event.message_str, (0, 1))
    action = args[0].lower() if args else "status"
    umo = str(event.unified_msg_origin or "")

    if action in ("on", "off"):
        if not umo:
            return event.plain_result("❌ 没能识别出会话，暂时无法开启概率回复。")

        if action == "on":
            opened = _enabled_sessions()
            if umo not in opened and len(opened) >= MAX_SESSIONS:
                return event.plain_result(
                    f"❌ 已经有 {MAX_SESSIONS} 个会话开着概率回复了，先关掉几个再加吧。"
                )
            _write_session(umo, enabled=True)
            await _ensure_job(plugin, umo, enabled=True)
            return event.plain_result(
                f"🎲 概率回复已对本会话开启：每 3 小时跑一次 {SCRIPT_NAME}，命中才开口，"
                "其余时候完全安静。"
            )

        _write_session(umo, enabled=False)
        await _ensure_job(plugin, umo, enabled=False)
        return event.plain_result("🔇 概率回复已对本会话关闭，脚本那边不会再打扰了。")

    if action in ("status", "state"):
        return event.plain_result(await _format_status(plugin, umo))

    if action in ("list", "sessions"):
        return event.plain_result(await _format_list(plugin))

    raise ArgsInputError(action, "on / off / status / list", get_help_text("rc"))


async def _format_status(plugin, umo: str) -> str:
    """本会话的开关状态：命中次数、下次判定时间、还有几个会话开着。"""
    state = _read_state()
    entry = _session_state(state, umo)
    nxt = _next_run_local(await _find_job(plugin, umo))
    when = f"，下次判定 {nxt:%Y-%m-%d %H:%M:%S}" if nxt else ""
    others = [u for u in _enabled_sessions(state) if u != umo]
    tail = f"\n另有 {len(others)} 个会话开着，/rc list 可以看。" if others else ""
    return (
        f"🎲 概率回复：{'开启' if entry.get('enabled') else '关闭'}"
        f"（本会话已命中 {int(entry.get('hits') or 0)} 次）{when}\n"
        f"当前会话：{umo or '（无法识别）'}{tail}"
    )


async def _format_list(plugin) -> str:
    """列出所有开着概率回复的会话。"""
    opened = _enabled_sessions()
    if not opened:
        return "🎲 现在没有会话开着概率回复，发 /rc on 就能给自己这个会话开上。"

    lines = [f"🎲 概率回复共 {len(opened)} 个会话开启："]
    for umo, entry in list(opened.items())[:MAX_LIST]:
        nxt = _next_run_local(await _find_job(plugin, umo))
        when = f"，下次 {nxt:%m-%d %H:%M}" if nxt else ""
        lines.append(f"- {umo}（命中 {int(entry.get('hits') or 0)} 次{when}）")
    if len(opened) > MAX_LIST:
        lines.append(f"……还有 {len(opened) - MAX_LIST} 个没列出来。")
    return "\n".join(lines)


def _migrate_legacy() -> None:
    """把旧版「全局一份」的状态搬成按会话存放（顶层 session + enabled 的那版）。"""
    state = storage.load_json(STATE_FILE)
    if not state or "sessions" in state:
        return
    umo = str(state.get("session") or "")
    if not umo:
        logger.warning("概率回复旧状态里没有会话信息，已跳过迁移")
        return
    entry = {
        key: state[key]
        for key in ("enabled", "hits", "last_text", "last_at")
        if key in state
    }
    storage.save_json(STATE_FILE, {"sessions": {umo: entry}})
    logger.info(f"概率回复状态已迁移为按会话存放：{umo}")


def _next_run_local(job: Any) -> datetime | None:
    """把定时任务的下次运行时间换算成本地时区。

    调度器写进库的是 UTC 时间，而字段是 `DateTime(timezone=False)`，时区信息
    落库时被丢掉；直接格式化会把 UTC 当本地时间来显示。这里先补上 UTC，
    再转到插件当前时区。
    """
    nxt = getattr(job, "next_run_time", None)
    if not isinstance(nxt, datetime):
        return None
    if nxt.tzinfo is None:  # 库里统一按 UTC 存，但不带时区
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt.astimezone(timeutil.get_timezone())


async def _find_job(plugin, umo: str) -> Any:
    """找本会话的那条概率回复任务。"""
    return await cron.find_job(plugin, ORIGIN, umo)


def _read_state() -> dict:
    """读取状态；文件缺失或损坏都当作「一个会话都没开」。"""
    state = storage.load_json(STATE_FILE)
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    return state


def _session_state(state: dict, umo: str) -> dict:
    """取某个会话的状态；不存在或类型不对时返回空字典。"""
    entry = state.get("sessions", {}).get(umo)
    return entry if isinstance(entry, dict) else {}


def _enabled_sessions(state: dict | None = None) -> dict[str, dict]:
    """所有开着概率回复的会话：{umo: 该会话的状态}。"""
    sessions = (state if state is not None else _read_state()).get("sessions", {})
    return {
        str(umo): entry
        for umo, entry in sessions.items()
        if isinstance(entry, dict) and entry.get("enabled")
    }


def _write_session(umo: str, **fields: Any) -> dict:
    """更新某个会话的状态并落盘。"""
    state = _read_state()
    entry = dict(_session_state(state, umo))
    entry.update(fields)
    entry["updated_at"] = timeutil.now().strftime("%Y-%m-%d %H:%M:%S")
    state["sessions"][umo] = entry
    state["updated_at"] = entry["updated_at"]
    storage.save_json(STATE_FILE, state)  # 写失败时 core.storage 会记日志
    return entry


async def _reconcile_jobs(plugin) -> None:
    """把库里遗留的概率回复任务同步到当前状态：没开着的会话，任务一律停掉。

    旧版是「全局一条任务、关掉时只停用不断开」，这里顺手把状态与任务
    对齐，免得留着一条永远空转的任务。
    """
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return
    opened = _enabled_sessions()
    for job in await cron_mgr.list_jobs("basic"):
        data = cron.payload(job)
        if data.get("origin") != ORIGIN:
            continue
        umo = str(data.get("umo") or data.get("session") or "")
        if not umo or umo in opened or not getattr(job, "enabled", False):
            continue
        try:
            await cron_mgr.update_job(job.job_id, enabled=False)
            logger.info(f"概率回复任务已停用（会话 {umo} 未开启）")
        except Exception as e:  # noqa: BLE001 - 单个任务失败不该影响其他恢复
            logger.error(f"停用会话 {umo} 的概率回复任务失败：{e}")


async def _ensure_job(plugin, umo: str, enabled: bool | None = None) -> Any:
    """确保本会话有一条 basic 任务，并按开关决定要不要调度。

    重启后 basic 任务不会自动带回处理器，所以这里既补绑定，也补调度，
    保证「关掉就彻底安静、开着就到点掷骰」。会话没开、也还没建过任务时
    不建任务，免得留下一堆用不上的空任务。
    """
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return None

    entry = _session_state(_read_state(), umo)
    want = bool(entry.get("enabled")) if enabled is None else bool(enabled)
    try:
        job = await _find_job(plugin, umo)
        if job is None:
            if not want:
                return None
            return await cron_mgr.add_basic_job(
                name=JOB_NAME,
                cron_expression=CRON,
                handler=partial(_fire, plugin),
                description=(
                    f"概率回复（/rc 控制）：跑 {SCRIPT_NAME} 掷骰，命中才叫一次模型"
                    f"；投递到 {umo}"
                ),
                timezone=TIMEZONE,
                payload={
                    "origin": ORIGIN,
                    "session": umo,
                    "umo": umo,
                    "desc": "概率回复（/rc 控制）：脚本掷骰，命中才开口",
                },
                enabled=True,
                persistent=True,
            )
        cron_mgr._basic_handlers[job.job_id] = partial(_fire, plugin)
        if bool(getattr(job, "enabled", False)) != want:
            job = await cron_mgr.update_job(job.job_id, enabled=want)
        elif want:
            cron_mgr._schedule_job(job)  # 重启后重新登记调度
        return job
    except Exception as e:  # noqa: BLE001 - 任务登记失败不应拖垮插件加载
        logger.error(f"概率回复任务初始化失败（{umo}）：{e}")
        return None


async def _run_script() -> tuple[int, str]:
    """在 scripts/ 目录里跑一次掷骰脚本，返回 (退出码, 合并后的输出)。"""
    script = SCRIPT
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            cwd=str(script.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:  # 脚本不在 / 解释器起不来
        return 127, f"（脚本无法启动：{e}）"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:  # 进程已经自己退出了
            pass
        await proc.wait()
        return 124, "（脚本超时，已中止本次运行）"
    code = proc.returncode if proc.returncode is not None else 0
    return code, out.decode("utf-8", "replace")


async def _compose(plugin, umo: str, last_text: str) -> str:
    """命中后生成一个问题：优先让模型写，模型不可用就退回兜底问题。"""
    try:
        provider_id = await plugin.context.get_current_chat_provider_id(umo)
        resp = await asyncio.wait_for(
            plugin.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=(
                    "现在主动问他一个问题。"
                    + (
                        f"上一次已经问过「{last_text}」，这次换个话题。"
                        if last_text
                        else ""
                    )
                ),
                system_prompt=SYSTEM_PROMPT,
            ),
            timeout=LLM_TIMEOUT,
        )
        text = (resp.completion_text or "").strip()
        if text:
            return text
        logger.warning("概率回复文案为空，本轮改用兜底问题")
    except Exception as e:  # noqa: BLE001 - 模型不可用也要照常提问
        logger.warning(f"概率回复文案生成失败，本轮改用兜底问题：{e}")

    candidates = [t for t in FALLBACKS if t != last_text]
    return random.choice(candidates or list(FALLBACKS))


async def _fire(plugin, **kwargs: Any) -> None:
    """概率回复的处理器：本会话开关关着或脚本没命中，就一个字都不说。"""
    umo = str(kwargs.get("umo") or kwargs.get("session") or "")
    if not umo:
        logger.error("概率回复缺少投递目标，本轮跳过")
        return

    state = _read_state()
    entry = _session_state(state, umo)
    if not entry.get("enabled"):  # 双重保险：任务被误调度时也不说话
        logger.debug(f"概率回复在会话 {umo} 处于关闭状态，本轮跳过")
        return

    code, raw = await _run_script()
    if code not in (0, 1):  # 脚本自己出问题：记一笔日志，但不打扰他
        logger.error(f"掷骰脚本异常（退出码 {code}）：{raw.strip()[:200]}")
        return
    if "HIT" not in raw:  # MISS：本轮连一次 LLM 调用都没有
        logger.debug(f"概率回复在会话 {umo} 本轮未命中（脚本判定），静默通过")
        return

    text = await _compose(plugin, umo, str(entry.get("last_text") or ""))
    try:
        await plugin.context.send_message(umo, MessageChain([Plain(text)]))
    except Exception as e:  # noqa: BLE001 - 发送失败不应影响插件运行
        logger.error(f"概率回复发送失败：{e}")
        return
    _write_session(
        umo,
        last_text=text,
        last_at=timeutil.now().strftime("%Y-%m-%d %H:%M:%S"),
        hits=int(entry.get("hits") or 0) + 1,
    )
