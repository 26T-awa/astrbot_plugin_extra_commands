"""命令参数解析。

AstrBot 会把消息里的 @ 段渲染成 ` @昵称(QQ号) ` 写进 `event.message_str`，
昵称里的空格会被 `str.split()` 当成参数分隔符；所以「目标用户」一律用
`parse_target_id()` 从消息末尾的 `(QQ号)` 里取，不要用 split() 的结果。
"""

import re

from .exceptions import TooFewArgsError, TooManyArgsError


def split_args(message_str: str) -> list[str]:
    """按空白切分消息并去掉指令本身，返回参数列表（不校验数量）。"""
    return message_str.strip().split()[1:]


def parse_args(message_str: str, bounds: tuple[int, int]) -> list[str]:
    """按空白切分并校验参数数量，`bounds` 形如 (最少, 最多)。

    数量不符时抛出 TooFewArgsError / TooManyArgsError，返回值不含指令本身。
    """
    parts = message_str.strip().split()
    count = len(parts) - 1  # 去掉指令本身后的参数数量
    if count < bounds[0]:
        raise TooFewArgsError(count, bounds[0])
    if count > bounds[1]:
        raise TooManyArgsError(count, bounds[1])
    return parts[1:]


def parse_target_id(message_str: str) -> str:
    """取出消息里的目标用户 ID。

    支持 `@昵称 (12345)` 与裸数字 `12345` 两种写法，取不到时返回空串。
    """
    match = re.search(r"\((\d{5,})\)\s*$", message_str) or re.search(
        r"(?<!\d)(\d{5,})\s*$", message_str
    )
    return match.group(1) if match else ""
