"""/alarm：把闹钟登记成 AstrBot 的定时任务。

- `set <时间> <描述>` 支持相对时间（+30s / +5m / +2h / +1d）、时间戳与日期时间；
  结尾加 `-llm` 时到点唤醒 LLM 由它组织语言发提醒，否则由插件直接发消息（不花 token）。
- `list` 查看本会话的闹钟，`del #<编号>` 取消闹钟。
- 旧的 `alarms.json` 会在插件启动时迁移成定时任务并改名存档。
"""

import asyncio
import time
from datetime import datetime, timezone
from functools import partial
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult
from astrbot.api.message_components import Plain

from ..core import cron, storage, timeutil
from ..core.args import parse_args
from ..core.exceptions import ArgsInputError, TooFewArgsError, TooManyArgsError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level

PER_SESSION = 5  # 单个会话内允许同时存在的闹钟数量
MAX_TOTAL = 50  # 所有会话合计的闹钟总数上限
DESC_MAX_LEN = 100  # 闹钟描述的字符数上限
ORIGIN = "extra_commands"  # 本插件登记的闹钟（写在定时任务 payload 里）
TOOL_ORIGIN = "tool"  # 由工具直接登记的提醒任务

_lock = asyncio.Lock()  # /alarm set 与 /alarm del 串行执行，避免同时操作定时任务管理器


async def setup(plugin) -> None:
    """插件启动时调用：迁移旧闹钟，并给不经过 LLM 的闹钟重新绑上处理器。"""
    try:
        await _migrate_legacy(plugin)
    except Exception as e:  # noqa: BLE001 - 迁移失败不能拖垮插件加载
        logger.error(f"迁移旧闹钟失败：{e}")
    try:
        await _bind_basic_handlers(plugin)
    except Exception as e:  # noqa: BLE001 - 绑定失败只影响 basic 闹钟
        logger.error(f"绑定闹钟处理器失败：{e}")


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """设置、查看或取消闹钟（需 member 及以上）。"""
    ensure_level(event, Level.MEMBER)
    use_llm = event.message_str.endswith("-llm")
    args = parse_args(event.message_str, (0, 4))[0:3]  # 忽略结尾的 -llm
    if not args:
        raise TooFewArgsError(0, 1)
    action = args[0].lower()

    if action == "list":  # 查
        if len(args) > 1:
            raise TooManyArgsError(len(args), 1)
        return event.plain_result(await _format_list(plugin, event))

    if action == "set":  # 设
        if len(args) <= 2:
            raise TooFewArgsError(len(args), 3)
        # args: [set, +30s, 打招呼]
        ts = timeutil.parse_alarm_time(args[1])
        if ts is None:
            raise ArgsInputError(args[1], "时间戳或日期时间", get_help_text("alarm"))
        if ts <= time.time():
            return event.plain_result(
                f"❌ 「{args[1]}」对应的时间已经过去了，请换一个将来的时间。\n"
                + get_help_text("alarm")
            )
        desc = args[2]
        if len(desc) > DESC_MAX_LEN:
            return event.plain_result(
                f"❌ 描述请控制在 {DESC_MAX_LEN} 个字符以内。"
            )
        async with _lock:  # 与 /alarm del 串行，避免同时操作定时任务管理器
            reply = await _add(plugin, event, ts, desc, use_llm)
        return event.plain_result(reply)

    if action == "del":  # 删
        if len(args) <= 1:
            raise TooFewArgsError(len(args), 2)
        raw_id = args[1].lstrip("#")  # args: [del, #1]
        if not raw_id.isdigit():
            raise ArgsInputError(args[1], "闹钟编号（数字）", get_help_text("alarm"))
        async with _lock:  # 与 /alarm set 串行，避免同时操作定时任务管理器
            reply = await _cancel(plugin, event, int(raw_id))
        return event.plain_result(reply)

    raise ArgsInputError(action, "set / list / del", get_help_text("alarm"))


def _note(desc: str) -> str:
    """写给被唤醒的 agent 的纸条：让它用自己的语气把提醒发出去。"""
    return (
        "你之前定下的闹钟到点了。请用你一贯的语气提醒对方这件事："
        f"「{desc}」。简短自然，最好能结合具体情境，可以说明是因为约好的时间到了才来提醒；"
        "不要提到定时任务、cron 之类的技术细节，"
        "然后调用 send_message_to_user 把提醒发出去。"
    )


def _run_ts(job: Any) -> float | None:
    """取一条定时任务的触发时间（Unix 秒）；取不到时返回 None。"""
    raw = cron.payload(job).get("run_at")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            pass
    next_run = getattr(job, "next_run_time", None)
    if isinstance(next_run, datetime):
        if next_run.tzinfo is None:  # 库里的时间统一按 UTC 存，但不带时区
            next_run = next_run.replace(tzinfo=timezone.utc)
        return next_run.timestamp()
    return None


async def _jobs(
    plugin, session: str | None = None, *, with_tool: bool = False
) -> list[Any]:
    """列出本插件登记的闹钟任务，可按会话过滤，按触发时间排序。"""
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return []
    try:
        jobs = await cron_mgr.list_jobs()
    except Exception as e:  # noqa: BLE001 - 读不到就当作没有闹钟
        logger.error(f"读取定时任务失败：{e}")
        return []
    origins = (ORIGIN, TOOL_ORIGIN) if with_tool else (ORIGIN,)
    picked = [
        job
        for job in jobs
        if cron.payload(job).get("origin") in origins
        and (session is None or cron.payload(job).get("session") == session)
    ]
    return sorted(picked, key=lambda job: _run_ts(job) or 0.0)


async def _format_list(plugin, event: AstrMessageEvent, with_tool: bool = True) -> str:
    """列出当前会话的闹钟。"""
    jobs = await _jobs(plugin, event.unified_msg_origin, with_tool=with_tool)
    if not jobs:
        return (
            "📭 本会话还没有闹钟，可用 /alarm set [时间] [描述] 设置一个。\n"
            + get_help_text("alarm")
        )

    now = time.time()
    # 本插件登记的闹铃和后台任务（工具直接建的）会混在一起，分开计数更清楚
    alarm_n = sum(1 for job in jobs if cron.payload(job).get("origin") == ORIGIN)
    head = f"⏰ 本会话待触发闹钟（共 {len(jobs)} 个"
    if alarm_n != len(jobs):
        head += f"，其中闹铃 {alarm_n}/{PER_SESSION}"
    head += "）："
    lines = [head]
    for job in jobs:
        payload = cron.payload(job)
        ts = _run_ts(job)
        if ts is None:
            when, left = "时间未知", ""
        else:
            when = timeutil.format_ts(ts)
            left = f"（{timeutil.format_duration(ts - now)}后）"
        how = "LLM" if getattr(job, "job_type", "") == "active_agent" else "直发"
        alarm_id = payload.get("alarm_id")
        # 工具任务没有 alarm_id / desc，退回用任务名，免得显示成「#? · （LLM）」
        tag = f"#{alarm_id} " if alarm_id else ""
        desc = payload.get("desc") or getattr(job, "name", "") or "（无描述）"
        lines.append(f"{tag}{when}{left}· {desc}（{how}）")
    lines.append("以上闹钟都已登记在 AstrBot 后台的「未来任务」里。")
    return "\n".join(lines)


async def _create_job(
    plugin,
    cron_mgr: Any,
    *,
    name: str,
    desc: str,
    payload: dict[str, Any],
    run_at: datetime,
    use_llm: bool,
) -> Any:
    """登记一条闹钟定时任务，返回创建好的任务对象。

    use_llm 为真：active_agent 任务，到点唤醒主 agent，让它自己组织语言发提醒；
    use_llm 为假：basic 任务，到点由插件直接发消息，不花 token。
    """
    if use_llm:
        return await cron_mgr.add_active_job(
            name=name,
            cron_expression=None,
            payload={**payload, "note": _note(desc)},
            description=desc,
            run_once=True,
            run_at=run_at,
        )

    # add_basic_job 只能建循环任务，所以先建成「未启用」，再补上
    # run_once / run_at 并启用；中间出错就把半成品删掉，不留垃圾。
    job = await cron_mgr.add_basic_job(
        name=name,
        cron_expression=None,
        handler=partial(_fire, plugin),
        description=desc,
        payload=payload,
        enabled=False,
        persistent=True,
    )
    try:
        updated = await cron_mgr.update_job(
            job.job_id,
            run_once=True,
            cron_expression=None,
            payload=payload,
            enabled=True,
        )
    except Exception:
        await cron_mgr.delete_job(job.job_id)
        raise
    return updated or job


async def _add(
    plugin, event: AstrMessageEvent, ts: float, desc: str, use_llm: bool
) -> str:
    """把闹钟登记成 AstrBot 的定时任务，返回回复文案。"""
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return "❌ 当前 AstrBot 没有可用的定时任务管理器，无法设置闹钟。"

    umo = event.unified_msg_origin
    jobs = await _jobs(plugin)
    same_session = [job for job in jobs if cron.payload(job).get("session") == umo]
    if len(same_session) >= PER_SESSION:
        return (
            f"❌ 本会话最多 {PER_SESSION} 个闹钟，"
            "请先用 /alarm del [编号] 取消一个。"
        )
    if len(jobs) >= MAX_TOTAL:
        return f"❌ 闹钟总数已达上限（{MAX_TOTAL}）。"

    now = timeutil.now()
    run_at = datetime.fromtimestamp(ts, timeutil.get_timezone())
    alarm_id = (
        max(
            (int(cron.payload(job).get("alarm_id") or 0) for job in jobs),
            default=0,
        )
        + 1
    )

    try:
        job = await _create_job(
            plugin,
            cron_mgr,
            name=f"闹钟 #{alarm_id}",
            desc=desc,
            payload={
                "origin": ORIGIN,
                "alarm_id": alarm_id,
                "desc": desc,
                "umo": umo,
                "session": umo,
                "creator": event.get_sender_name() or event.get_sender_id(),
                "creator_id": event.get_sender_id(),
                "created": now.timestamp(),
                "run_at": run_at.isoformat(),
            },
            run_at=run_at,
            use_llm=use_llm,
        )
    except Exception as e:  # noqa: BLE001 - 登记失败要给用户一个可见的提示
        logger.error(f"登记闹钟失败：{e}")
        return f"❌ 闹钟登记失败：{e}"

    how = (
        "到点唤醒 LLM，让它自己发提醒" if use_llm else "到点直接发提醒，不调用 LLM"
    )
    return (
        f"⏰ 闹钟已设置（#{alarm_id}，任务 ID {job.job_id}）\n"
        f"时间：{timeutil.format_ts(ts)}"
        f"（{timeutil.format_duration(ts - now.timestamp())}后）\n"
        f"描述：{desc}\n"
        f"方式：{how}\n"
        "已同步到 AstrBot 后台的「未来任务」，在那里也能查看或删除。"
    )


async def _cancel(plugin, event: AstrMessageEvent, alarm_id: int) -> str:
    """取消指定闹钟，返回回复文案。"""
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return "❌ 当前 AstrBot 没有可用的定时任务管理器。"

    session = event.unified_msg_origin
    for job in await _jobs(plugin, session):
        payload = cron.payload(job)
        if int(payload.get("alarm_id") or 0) != alarm_id:
            continue

        sender = event.get_sender_id()
        if payload.get("creator_id") != sender and Level.name_of(sender) == "member":
            return "❌ 只能取消自己设置的闹钟。"

        try:
            await cron_mgr.delete_job(job.job_id)
        except Exception as e:  # noqa: BLE001 - 删除失败要给用户一个可见的提示
            logger.error(f"取消闹钟 #{alarm_id} 失败：{e}")
            return f"❌ 取消闹钟 #{alarm_id} 失败：{e}"
        return f"🗑️ 已取消闹钟 #{alarm_id}（{payload.get('desc', '')}）。"

    return f"❌ 没有编号为 #{alarm_id} 的闹钟。"


async def _fire(plugin, **kwargs: Any) -> None:
    """basic 闹钟的处理器：到点直接发提醒，不经过 LLM。"""
    umo = str(kwargs.get("umo") or kwargs.get("session") or "")
    if not umo:
        logger.error("闹钟缺少投递目标，无法发送提醒")
        return

    alarm_id = kwargs.get("alarm_id", "?")
    text = f"⏰ 闹钟响啦（#{alarm_id}）：{kwargs.get('desc', '')}"
    created = kwargs.get("created")
    if kwargs.get("creator") and created:
        text += f"\n—— {kwargs['creator']} 于 {timeutil.format_ts(created)} 设置"
    try:
        await plugin.context.send_message(umo, MessageChain([Plain(text)]))
    except Exception as e:  # noqa: BLE001 - 发送失败不应影响插件运行
        logger.error(f"闹钟 #{alarm_id} 提醒发送失败：{e}")


async def _bind_basic_handlers(plugin) -> None:
    """把 basic 闹钟重新绑回处理器：重启之后它们照样有人负责发消息。

    CronJobManager 只在新建 basic 任务时接收处理器，恢复已有任务只能直接
    写它的处理器表，所以这里会用到它的私有属性。
    """
    cron_mgr = cron.manager(plugin)
    if cron_mgr is None:
        return

    bound = 0
    for job in await cron_mgr.list_jobs("basic"):
        if cron.payload(job).get("origin") != ORIGIN:
            continue
        cron_mgr._basic_handlers[job.job_id] = partial(_fire, plugin)
        bound += 1
    if bound:
        logger.info(f"额外命令插件重新绑定了 {bound} 个不经过 LLM 的闹钟")


async def _migrate_legacy(plugin) -> None:
    """把旧版 alarms.json 里还没响的闹钟转成定时任务，再把文件改名存档。"""
    legacy_path = storage.LEGACY_ALARM_FILE
    if not legacy_path.is_file():
        return

    cron_mgr = cron.manager(plugin)
    stored = storage.load_json(legacy_path)
    items = stored.get("items") if isinstance(stored, dict) else None
    records = items if isinstance(items, list) else []

    now = time.time()
    moved = 0
    for record in records:
        if cron_mgr is None or not isinstance(record, dict):
            continue
        try:
            ts = float(record["ts"])
            umo = str(record["umo"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts <= now or not umo:  # 已经过期，或者不知道要发往哪里
            continue

        desc = str(record.get("desc", ""))
        run_at = datetime.fromtimestamp(ts, timeutil.get_timezone())
        try:
            await _create_job(
                plugin,
                cron_mgr,
                name=f"闹钟 #{record.get('id', '?')}",
                desc=desc,
                payload={
                    "origin": ORIGIN,
                    "alarm_id": int(record.get("id") or 0),
                    "desc": desc,
                    "umo": umo,
                    "session": umo,
                    "creator": str(record.get("creator") or ""),
                    "creator_id": str(record.get("creator_id") or ""),
                    "created": float(record.get("created") or now),
                    "run_at": run_at.isoformat(),
                },
                run_at=run_at,
                use_llm=False,
            )
            moved += 1
        except Exception as e:  # noqa: BLE001 - 单条失败不影响其它闹钟
            logger.error(f"迁移旧闹钟 #{record.get('id')} 失败：{e}")

    try:
        legacy_path.rename(legacy_path.with_name(legacy_path.name + ".bak"))
    except OSError as e:
        logger.error(f"重命名旧闹钟文件失败：{e}")
        return
    if moved:
        logger.info(f"额外命令插件把 {moved} 个旧闹钟迁移成了定时任务")
