"""时间与时区工具。

插件有一个「当前默认时区」，默认是北京时间（UTC+8），`/time setzone` 可以改；
时间显示、闹钟时间解析都以它为准。
"""

import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_OFFSET_HOURS = 8  # 默认时区：北京时间（UTC+8）

# 常见时区缩写。CST 在国内一般指北京时间，这里按 UTC+8 处理
TZ_ABBR: dict[str, tzinfo] = {
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "CST": timezone(timedelta(hours=8), "CST"),
    "JST": timezone(timedelta(hours=9), "JST"),
    "KST": timezone(timedelta(hours=9), "KST"),
    "EST": timezone(timedelta(hours=-5), "EST"),
    "EDT": timezone(timedelta(hours=-4), "EDT"),
    "PST": timezone(timedelta(hours=-8), "PST"),
}

_current: tzinfo = timezone(timedelta(hours=DEFAULT_OFFSET_HOURS))
"""当前默认时区，通过 get_timezone() / set_timezone() 读写。"""


def get_timezone() -> tzinfo:
    """当前默认时区。"""
    return _current


def set_timezone(tz: tzinfo) -> None:
    """设置当前默认时区。"""
    global _current
    _current = tz


def resolve_timezone(raw: str) -> tzinfo:
    """把用户输入解析成 tzinfo。

    支持三种写法：`8` / `+8` / `-3.5`（相对 UTC 的小时偏移）、`UTC` / `CST`
    这样的缩写、`Asia/Shanghai` 这样的地区名。认不出时抛出 ValueError。
    """
    text = raw.strip()
    if not text:
        raise ValueError("时区不能为空")
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return timezone(timedelta(hours=float(text)))
    if text.upper() in TZ_ABBR:
        return TZ_ABBR[text.upper()]
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"未知时区：{raw}") from e


def now() -> datetime:
    """当前时区的时间。"""
    return datetime.now(get_timezone())


def format_ts(ts: float) -> str:
    """把 Unix 秒格式化成当前时区的字符串。"""
    return datetime.fromtimestamp(ts, get_timezone()).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    """把秒数粗略格式化成「x天x小时x分钟」，不足一分钟时按秒显示。"""
    remain = int(max(0.0, seconds))
    days, remain = divmod(remain, 86400)
    hours, remain = divmod(remain, 3600)
    minutes, secs = divmod(remain, 60)

    chunks = []
    if days:
        chunks.append(f"{days}天")
    if hours:
        chunks.append(f"{hours}小时")
    if minutes:
        chunks.append(f"{minutes}分钟")
    if not chunks:
        chunks.append(f"{secs}秒")
    return "".join(chunks)


def parse_alarm_time(raw: str) -> float | None:
    """解析闹钟时间，失败时返回 None。

    支持三种写法：
    - 相对时间：+30s / +5m / +2h / +1d（s 秒、m 分、h 时、d 天）
    - Unix 时间戳：秒（10 位）或毫秒（13 位及以上）
    - 日期时间：2026-09-27/07:30、09-27/07:30、07:30 等
    """
    text = raw.strip()
    if not text:
        return None

    current = now()

    relative = re.fullmatch(r"\+(\d+(?:\.\d+)?)([smhd])", text, re.I)
    if relative:  # 相对时间：以当前时刻为起点
        unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return current.timestamp() + float(relative.group(1)) * unit[
            relative.group(2).lower()
        ]

    if re.fullmatch(r"\d{1,13}", text):  # 时间戳：13 位及以上按毫秒处理
        return int(text) / 1000 if len(text) >= 13 else float(int(text))

    for fmt in (
        "%Y-%m-%d/%H:%M:%S",
        "%Y-%m-%d/%H:%M",
        "%Y-%m-%d",
        "%m-%d/%H:%M:%S",
        "%m-%d/%H:%M",
        "%m-%d",
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt.startswith("%H"):  # 只给时刻：补上今天
            parsed = parsed.replace(year=current.year, month=current.month, day=current.day)
        elif fmt.startswith("%m"):  # 只给月日：补上今年
            parsed = parsed.replace(year=current.year)
        parsed = parsed.replace(tzinfo=get_timezone())
        if fmt.startswith("%H") and parsed <= current:  # 今天已过：顺延到明天
            parsed += timedelta(days=1)
        return parsed.timestamp()
    return None
