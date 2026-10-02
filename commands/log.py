"""/log：查看 AstrBot 最近的内存日志（仅 owner / admin 可用）。

AstrBot 用 `LogBroker` 在内存里缓存最近 500 条日志（实例由
`astrbot.core.log.LogManager` 持有），本模块只负责把日志取出来用：

    取日志 → 剥掉 ANSI 颜色码 → 导出一份文件 → 交给模型读一遍

    /log [n]        取最近 n 条日志（默认 50，上限 500），让模型读完给出结论
    /log -f [n]     只把日志导出成文件发出来，不调用模型
    /log [n] <问题>  把问题一并交给模型，让它针对日志回答

日志文件写在 `<数据目录>/logs/` 下，每次导出新的一份（文件名带时间戳）。
"""

import asyncio
import logging
import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import File, Plain
from astrbot.core.log import LogManager

from ..core import storage, timeutil
from ..core.args import split_args
from ..core.exceptions import ArgsInputError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level

DEFAULT_COUNT = 50
MAX_COUNT = 500  # 与 LogBroker 的 CACHED_SIZE 一致：缓存里最多就这么多条
MAX_CHARS = 12000  # 交给模型的字符上限，超长时只保留最新的那一段
LLM_TIMEOUT = 60.0
FILE_FLAGS = {"-f", "-file", "-nollm"}  # 都表示「只发文件，不叫模型」
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")  # 日志里的终端颜色码

SYSTEM_PROMPT = (
    "你是 AstrBot 机器人的运维助手。用户会把机器人最近的日志贴给你。"
    "请通读日志，用中文简明地指出其中的报错、异常和值得注意的地方；"
    "没有问题就如实说明，不要编造日志里不存在的内容。"
)

WRITE_FAILED = "⚠️ 日志文件写入失败，请查看日志。"
EMPTY_CACHE = "⚠️ 取不到日志：AstrBot 的内存日志缓存是空的。"
LLM_FAILED = "⚠️ 模型没能给出分析结果，日志文件还是先发给你。"


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """把最近的内存日志发出来，默认再让模型读一遍（需 owner / admin）。"""
    ensure_level(event, Level.ADMIN)
    count, only_file, question = _parse_args(event.message_str)

    lines = _read_logs(count)
    if not lines:
        return event.plain_result(EMPTY_CACHE)

    logger.info(
        f"收到 /log：{event.get_sender_name()}（{event.get_sender_id()}）"
        f"导出最近 {len(lines)} 条日志"
    )
    path = storage.write_log_file(_file_name(), _dump(lines))
    if path is None:
        return event.plain_result(WRITE_FAILED)

    if only_file:
        answer = f"📄 已导出最近 {len(lines)} 条日志。"
    else:
        body = _truncate("\n".join(lines), MAX_CHARS)
        answer = await _ask(plugin, event, body, question)

    return event.chain_result(
        # 文件段在 aiocqhttp 上是单独一条消息，所以文本放前面、文件跟后面
        [Plain(answer), File(name=path.name, file=str(path))]
    )


# ==================== 参数与文案 ====================


def _parse_args(message_str: str) -> tuple[int, bool, str]:
    """解析参数，返回 (条数, 是否只发文件, 交给模型的问题)。

    数字是条数，`-f` 一类的开关表示不叫模型，剩下的词拼成问题。
    """
    count, only_file, words = DEFAULT_COUNT, False, []
    for arg in split_args(message_str):
        if arg.lower() in FILE_FLAGS:
            only_file = True
        elif arg.isdigit():
            count = int(arg)
            if not 1 <= count <= MAX_COUNT:
                raise ArgsInputError(
                    f"数值{count}∉[1, {MAX_COUNT}]",
                    f"{count}∈[1, {MAX_COUNT}]",
                    get_help_text("log"),
                )
        elif arg.startswith("-"):
            raise ArgsInputError(arg, "-f / 条数 / 问题", get_help_text("log"))
        else:
            words.append(arg)
    return count, only_file, " ".join(words)


def _dump(lines: list[str]) -> str:
    """把日志行拼成导出文件的内容，开头写一行来源说明。"""
    stamp = timeutil.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# AstrBot 日志导出：最近 {len(lines)} 条（{stamp}）"
    return "\n".join([header, *lines]) + "\n"


def _file_name() -> str:
    """导出文件名：带时间戳，不会互相覆盖。"""
    return f"astrbot-log-{timeutil.now().strftime('%Y%m%d-%H%M%S')}.txt"


def _truncate(text: str, limit: int) -> str:
    """超长时只保留最新的一段，并标注前面被省略过。"""
    if len(text) <= limit:
        return text
    return "（较早的日志已省略）\n" + text[-limit:]


# ==================== 日志读取 ====================


def _read_logs(count: int) -> list[str]:
    """取最近 count 条日志，剥掉 ANSI 颜色码；取不到时返回空列表。"""
    if count <= 0:  # 切片里的 -0 会把整份缓存都取出来，这里挡一下
        return []
    entries = list(_log_cache())[-count:]
    lines = []
    for entry in entries:
        raw = entry.get("data", "") if isinstance(entry, dict) else entry
        line = ANSI_RE.sub("", str(raw)).rstrip()
        if line:
            lines.append(line)
    return lines


def _log_cache():
    """拿到 LogBroker 的日志缓存（deque），拿不到时返回空元组。"""
    broker = getattr(LogManager, "_log_broker", None)
    if broker is None:  # 兜底：LogQueueHandler 自己也攥着同一个 broker
        for handler in logging.getLogger("astrbot").handlers:
            broker = getattr(handler, "log_broker", None)
            if broker is not None:
                break
    return getattr(broker, "log_cache", ()) or ()


# ==================== 模型分析 ====================


def _prompt(body: str, question: str) -> str:
    """把日志和用户的问题拼成给模型的提问。"""
    ask = question or "请通读这份日志，用中文简要总结其中值得注意的地方。"
    return f"{ask}\n\n以下是 AstrBot 最近的日志：\n{body}"


async def _ask(plugin, event: AstrMessageEvent, body: str, question: str) -> str:
    """让模型读日志并给出结论；模型不可用时退回提示文案。"""
    try:
        provider_id = await plugin.context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
        resp = await asyncio.wait_for(
            plugin.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=_prompt(body, question),
                system_prompt=SYSTEM_PROMPT,
            ),
            timeout=LLM_TIMEOUT,
        )
        text = (resp.completion_text or "").strip()
        if text:
            return text
        logger.warning("日志分析返回空文案，本轮改用提示文案")
    except Exception as e:  # noqa: BLE001 - 模型不可用也要把文件发出去
        logger.warning(f"日志分析失败，本轮改用提示文案：{e}")
    return LLM_FAILED
