"""/rc：概率回复开关。

原理：注册一条 basic 定时任务，每 3 小时跑一次 `scripts/roll_ask.py` 掷骰——
- 未命中（MISS）：本轮直接结束，连一次 LLM 调用都没有；
- 命中（HIT）：用当前会话的模型生成一个问题并发送。
开关状态保存在 `randomchat_state.json`，关掉之后脚本不再掷骰，完全安静。
"""

import asyncio
import random
import sys
from datetime import datetime
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
    """插件启动时调用：确保概率回复是一条可用的定时任务。"""
    await _ensure_job(plugin)


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """开关概率回复：/rc on|off|status（需 admin）。"""
    ensure_level(event, Level.ADMIN)
    args = parse_args(event.message_str, (0, 1))
    action = args[0].lower() if args else "status"
    state = _read_state()

    if action in ("on", "off"):
        turn_on = action == "on"
        session = str(event.unified_msg_origin or state.get("session") or "")
        if turn_on and not session:
            return event.plain_result("❌ 没能识别出会话，暂时无法开启概率回复。")
        _write_state(enabled=turn_on, session=session)
        await _ensure_job(plugin, enabled=turn_on)
        if turn_on:
            return event.plain_result(
                f"🎲 概率回复已开启：每 3 小时跑一次 {SCRIPT_NAME}，命中才开口，其余时候完全安静。"
            )
        return event.plain_result("🔇 概率回复已关闭，脚本那边不会再打扰了。")

    if action in ("status", "state"):
        job = await cron.find_job(plugin, ORIGIN)
        nxt = getattr(job, "next_run_time", None)
        when = (
            f"，下次判定 {nxt:%Y-%m-%d %H:%M:%S}"
            if isinstance(nxt, datetime)
            else ""
        )
        return event.plain_result(
            f"🎲 概率回复：{'开启' if state.get('enabled') else '关闭'}"
            f"（已命中 {int(state.get('hits') or 0)} 次）{when}"
        )

    raise ArgsInputError(action, "on / off / status", get_help_text("rc"))


def _read_state() -> dict:
    """读取开关状态；文件缺失或损坏都当作「关闭」。"""
    return storage.load_json(STATE_FILE)


def _write_state(**fields: Any) -> dict:
    """更新状态并落盘。"""
    state = _read_state()
    state.update(fields)
    state["updated_at"] = timeutil.now().strftime("%Y-%m-%d %H:%M:%S")
    storage.save_json(STATE_FILE, state)  # 写失败时 core.storage 会记日志
    return state


async def _ensure_job(plugin, enabled: bool | None = None) -> Any:
    """确保概率回复是一条 basic 任务，并按开关决定要不要调度。

    重启后 basic 任务不会自动带回处理器，所以这里既补绑定，也补调度，
    保证「关掉就彻底安静、开着就到点掷骰」。
    """
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return None

    state = _read_state()
    want = bool(state.get("enabled")) if enabled is None else bool(enabled)
    session = str(state.get("session") or "")
    try:
        job = await cron.find_job(plugin, ORIGIN)
        if job is None:
            return await cron_mgr.add_basic_job(
                name=JOB_NAME,
                cron_expression=CRON,
                handler=partial(_fire, plugin),
                description=f"概率回复（/rc 控制）：跑 {SCRIPT_NAME} 掷骰，命中才叫一次模型",
                timezone=TIMEZONE,
                payload={
                    "origin": ORIGIN,
                    "session": session,
                    "umo": session,
                    "desc": "概率回复（/rc 控制）：脚本掷骰，命中才开口",
                },
                enabled=want,
                persistent=True,
            )
        cron_mgr._basic_handlers[job.job_id] = partial(_fire, plugin)
        if bool(getattr(job, "enabled", False)) != want:
            job = await cron_mgr.update_job(job.job_id, enabled=want)
        elif want:
            cron_mgr._schedule_job(job)  # 重启后重新登记调度
        return job
    except Exception as e:  # noqa: BLE001 - 任务登记失败不应拖垮插件加载
        logger.error(f"概率回复任务初始化失败：{e}")
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
    """概率回复的处理器：开关关着或脚本没命中，就一个字都不说。"""
    state = _read_state()
    if not state.get("enabled"):  # 双重保险：任务被误调度时也不说话
        logger.debug("概率回复开关处于关闭状态，本轮跳过")
        return

    umo = str(
        state.get("session") or kwargs.get("umo") or kwargs.get("session") or ""
    )
    if not umo:
        logger.error("概率回复缺少投递目标，本轮跳过")
        return

    code, raw = await _run_script()
    if code not in (0, 1):  # 脚本自己出问题：记一笔日志，但不打扰他
        logger.error(f"掷骰脚本异常（退出码 {code}）：{raw.strip()[:200]}")
        return
    if "HIT" not in raw:  # MISS：本轮连一次 LLM 调用都没有
        logger.debug("概率回复本轮未命中（脚本判定），静默通过")
        return

    text = await _compose(plugin, umo, str(state.get("last_text") or ""))
    try:
        await plugin.context.send_message(umo, MessageChain([Plain(text)]))
    except Exception as e:  # noqa: BLE001 - 发送失败不应影响插件运行
        logger.error(f"概率回复发送失败：{e}")
        return
    _write_state(
        last_text=text,
        last_at=timeutil.now().strftime("%Y-%m-%d %H:%M:%S"),
        hits=int(state.get("hits") or 0) + 1,
    )
