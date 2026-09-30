"""/time：显示时间，或查看 / 设置默认时区。"""

from datetime import datetime, tzinfo

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_args
from ..core.exceptions import ArgsInputError, TooFewArgsError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level
from ..core.timeutil import get_timezone, resolve_timezone, set_timezone

WEEKDAYS = "一二三四五六日"


def _time_text(tz: tzinfo) -> str:
    """当前时间与时间戳的展示文案。"""
    moment = datetime.now(tz)
    weekday = WEEKDAYS[moment.weekday()]
    return (
        f"🕒 当前时间：{moment:%Y-%m-%d %H:%M:%S}（{tz} 星期{weekday}）\n"
        f"🔢 Unix 时间戳：{int(moment.timestamp())}"
    )


def _parse_timezone(raw: str) -> tzinfo:
    """把用户输入解析成时区；认不出时抛出 ArgsInputError。"""
    try:
        return resolve_timezone(raw)
    except ValueError:
        raise ArgsInputError(
            raw, "时区（8 / UTC / Asia/Shanghai）", get_help_text("time")
        )


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """显示时间；`/time <时区>` 查看指定时区，`/time setzone <时区>` 改默认时区（需 member 及以上）。"""
    ensure_level(event, Level.MEMBER)
    args = parse_args(event.message_str, (0, 2))

    if not args:  # 无参数：当前默认时区
        return event.plain_result(_time_text(get_timezone()))

    if args[0].lower() == "setzone":
        if len(args) < 2:
            raise TooFewArgsError(len(args), 2)
        tz = _parse_timezone(args[1])
        set_timezone(tz)
        return event.plain_result(f"⚠️ 已设置默认时区为 {tz}\n{_time_text(tz)}")

    if len(args) == 1:  # 单个参数：按指定时区显示
        return event.plain_result(_time_text(_parse_timezone(args[0])))

    raise ArgsInputError(" ".join(args), "setzone <时区> 或单个时区", get_help_text("time"))
