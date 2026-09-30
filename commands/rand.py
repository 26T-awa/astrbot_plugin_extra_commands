"""/rand：生成随机数。"""

import random
import re

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_args
from ..core.exceptions import ArgsInputError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level

DEFAULT_RANGE = (0, 99)  # 默认范围
MAX_COUNT = 100  # 一次最多生成多少个

repeat = True  # 是否允许重复；由 /rand -r <true|false> 切换，插件重载后回到默认值


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """生成随机数（需 member 及以上）。"""
    ensure_level(event, Level.MEMBER)

    global repeat
    flag = re.search(r"-r\s+(\S+)", event.message_str, re.I)
    if flag:  # 只切换开关，不生成数字
        value = flag.group(1).lower()
        if value == "true":
            repeat = True
            return event.plain_result(
                "⚠️ /rand -r true 已启用重复，若要关闭请使用 /rand -r false"
            )
        if value == "false":
            repeat = False
            return event.plain_result(
                "⚠️ /rand -r false 已关闭重复，若要开启请使用 /rand -r true"
            )
        raise ArgsInputError(flag.group(1), "true/false", get_help_text("rand"))

    args = parse_args(event.message_str, (1, 3))  # 至少 1 个数字，最多 3 个
    numbers = []
    for arg in args:
        try:
            numbers.append(int(arg))
        except ValueError:
            raise ArgsInputError(arg, "整数", get_help_text("rand"))

    # ---- 位置参数：min / max / count ----
    low, high = DEFAULT_RANGE
    count = 1
    if len(numbers) == 1:  # 只给一个数时视为 max
        low, high = 0, numbers[0]
    elif len(numbers) >= 2:
        low, high = numbers[0], numbers[1]
    if len(numbers) == 3:
        count = numbers[2]

    size = high - low + 1
    if size <= 0:
        raise ArgsInputError(
            f"区间{low}>{high}", f"{low}<={high}", get_help_text("rand")
        )
    if not 1 <= count <= MAX_COUNT:
        raise ArgsInputError(
            f"数值{count}∉[1, {MAX_COUNT}]",
            f"{count}∈[1, {MAX_COUNT}]",
            get_help_text("rand"),
        )
    if not repeat and count > size:
        raise ArgsInputError(
            f"数值{count}∉[1, {size}]",
            f"{count}∈[1, {size}]",
            get_help_text("rand"),
        )

    drawn = (
        [random.randint(low, high) for _ in range(count)]
        if repeat
        else random.sample(range(low, high + 1), count)
    )

    if count == 1:
        return event.plain_result(f"🎲 随机数（{low}~{high}）：{drawn[0]}")
    note = "" if repeat else "，不重复"
    return event.plain_result(
        f"🎲 随机数（{low}~{high}，共 {count} 个{note}）："
        + "、".join(str(n) for n in drawn)
    )
