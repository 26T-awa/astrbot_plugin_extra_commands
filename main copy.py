"""额外命令插件：帮助、数据、随机数、时间、闹钟、日志与进程退出的实现。"""

import asyncio
import functools
import json
import os
import random
import re
import signal
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

try:  # 以包形式加载时优先使用相对导入
    from .help_text import (  # 命令帮助文本
        EHELP_TEXT,
        get_help_text,
        not_found_text,
    )
    from .exceptions import TooManyArgsError, TooFewArgsError  # 自定义异常
except ImportError:  # 兜底：插件被当作顶层模块加载时
    from help_text import (  # 命令帮助文本
        EHELP_TEXT,
        get_help_text,
        not_found_text,
    )
    from exceptions import TooManyArgsError, TooFewArgsError  # 自定义异常

try:  # AstrBot 路径工具，用于定位插件数据目录与日志文件
    from astrbot.core.utils.astrbot_path import (
        get_astrbot_data_path,
        get_astrbot_plugin_data_path,
    )
except ImportError:  # 兜底：AstrBot 版本较旧时按插件位置推断路径
    get_astrbot_data_path = None
    get_astrbot_plugin_data_path = None


# ==================== 常量 ====================

TZ_BEIJING = timezone(timedelta(hours=8))
"""北京时间（UTC+8）。"""

PLUGIN_DATA_NAME = "extra_commands"
"""在 AstrBot 的 plugin_data 下使用的目录名。"""

ADMIN_ONLY = "🚫 该指令仅管理员可用。"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

RAND_DEFAULT_RANGE = (0, 100)
RAND_MAX_COUNT = 20

DATA_MAX_KEYS = 200
DATA_MAX_KEY_LEN = 32
DATA_MAX_VALUE_LEN = 500

ALARM_PER_SESSION = 5
ALARM_MAX_TOTAL = 50

LOG_DEFAULT_COUNT = 10
LOG_MAX_COUNT = 50
LOG_MAX_CHARS = 1500
LOG_LINE_MAX_CHARS = 240


# ==================== 路径与文件工具 ====================


def _plugin_dir() -> Path:
    """插件自身所在目录。"""
    return Path(__file__).resolve().parent


def _plugin_data_dir() -> Path:
    """本插件的持久化目录：优先用 AstrBot 的 plugin_data，否则退回插件内 data/。"""
    if get_astrbot_plugin_data_path is not None:
        return Path(get_astrbot_plugin_data_path()) / PLUGIN_DATA_NAME
    return _plugin_dir() / "data"


def _log_file() -> Path:
    """AstrBot 的日志文件路径（默认 <data>/logs/astrbot.log）。"""
    base = (
        Path(get_astrbot_data_path())
        if get_astrbot_data_path is not None
        else _plugin_dir().parents[1]  # 插件位于 <root>/data/plugins/<name>/
    )
    return base / "logs" / "astrbot.log"


def _load_json(path: Path, default: Any) -> Any:
    """读取 JSON 文件；文件不存在或解析失败时返回默认值。"""
    if not path.is_file():
        return default
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"读取 {path.name} 失败：{e}")
        return default


def _save_json(path: Path, payload: Any) -> None:
    """原子写入 JSON：先写临时文件再替换，避免中途失败写坏原文件。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)
    except OSError as e:
        logger.error(f"写入 {path.name} 失败：{e}")


# ==================== 时间与文本工具 ====================


def _beijing_now() -> datetime:
    """当前北京时间。"""
    return datetime.now(TZ_BEIJING)


def _format_ts(ts: float) -> str:
    """把 Unix 秒格式化为北京时间字符串。"""
    return datetime.fromtimestamp(ts, TZ_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(seconds: float) -> str:
    """把秒数粗略格式化成「x 天 x 小时 x 分钟」。"""
    remain = int(max(0.0, seconds))
    days, remain = divmod(remain, 86400)
    hours, remain = divmod(remain, 3600)
    minutes = remain // 60
    chunks = []
    if days:
        chunks.append(f"{days} 天")
    if hours:
        chunks.append(f"{hours} 小时")
    if minutes:
        chunks.append(f"{minutes} 分钟")
    return " ".join(chunks) or "不到 1 分钟"


def _truncate(text: str, limit: int) -> str:
    """超长文本截断并加省略号。"""
    return text if len(text) <= limit else text[:limit] + "…"


def _strip_ansi(text: str) -> str:
    """去掉日志里的 ANSI 颜色控制符。"""
    return ANSI_RE.sub("", text)


def _parse_alarm_time(raw: str) -> float | None:
    """解析闹钟时间：支持 Unix 时间戳与多种日期时间写法，失败返回 None。

    只给时刻（如 07:30）时按「最近一次尚未到来的该时刻」计算，即今天已过则顺延一天。
    """
    raw = raw.strip()
    if raw.isdigit():
        value = int(raw)
        return value / 1000 if len(raw) >= 13 else float(value)  # 13 位按毫秒处理

    now = _beijing_now()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m-%d %H:%M:%S",
        "%m-%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt.startswith("%H"):  # 只给时刻：补上今天
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            elif fmt.startswith("%m"):  # 只给月日：补上今年
                parsed = parsed.replace(year=now.year)
            parsed = parsed.replace(tzinfo=TZ_BEIJING)
            if fmt.startswith("%H") and parsed <= now:  # 今天已过：顺延到明天
                parsed += timedelta(days=1)
            return parsed.timestamp()
        except ValueError:
            continue
    return None


# ==================== 日志读取 ====================


def _broker_log_cache() -> list[dict]:
    """读取 AstrBot 日志代理的内存缓存（最近 500 条）；不可用时返回空列表。"""
    try:
        from astrbot import logger as astrbot_logger
        from astrbot.core.log import LogQueueHandler
    except ImportError:
        return []
    for handler in astrbot_logger.handlers:
        if isinstance(handler, LogQueueHandler):
            return list(handler.log_broker.log_cache)
    return []


def _tail_log_file(count: int) -> list[str]:
    """兜底方案：读取 AstrBot 日志文件的最后若干行。"""
    path = _log_file()
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = list(deque(f, maxlen=count))
    except OSError as e:
        logger.error(f"读取日志文件失败：{e}")
        return []
    return [_truncate(_strip_ansi(line).rstrip(), LOG_LINE_MAX_CHARS) for line in lines]


def _recent_logs(count: int) -> list[str]:
    """取最近若干条日志：优先内存缓存，其次日志文件。"""
    entries = _broker_log_cache()
    if entries:
        return [
            _truncate(
                _strip_ansi(str(entry.get("data", ""))).strip(), LOG_LINE_MAX_CHARS
            )
            for entry in entries[-count:]
        ]
    return _tail_log_file(count)


# ==================== 进程退出 ====================


async def _quit_process(delay: float = 2.0) -> None:
    """延迟退出：先让回复消息送达，再触发 AstrBot 的退出流程。"""
    await asyncio.sleep(delay)
    logger.warning("额外命令插件执行 /forcequit，正在退出 AstrBot 进程")
    try:
        signal.raise_signal(signal.SIGINT)  # 优先走 AstrBot 的正常退出流程
        await asyncio.sleep(3)
    except Exception as e:  # noqa: BLE001 - 非主线程等场景下退回强制退出
        logger.warning(f"发送退出信号失败，将强制退出：{e}")
    os._exit(0)


# ==================== 参数异常 → 回复 ====================


def _args_error_to_reply(command: str):
    """装饰器：把参数数量异常转成「错误提示 + 该指令用法」的回复。"""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, event: AstrMessageEvent):
            try:
                async for result in func(self, event):
                    yield result
            except (TooFewArgsError, TooManyArgsError) as e:
                yield event.plain_result(f"❌ {e}\n{get_help_text(command) or ''}")

        return wrapper

    return decorator


@register("extra_commands", "_26T", "额外命令", "0.1")
class ExtraCommands(Star):
    """额外命令集合：帮助、数据、随机数、时间、闹钟、日志与进程退出。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self._data_dir = _plugin_data_dir()
        self._data_path = self._data_dir / "data.json"
        self._alarm_path = self._data_dir / "alarms.json"
        self._data_lock = asyncio.Lock()
        self._alarms: dict[int, dict[str, Any]] = {}
        self._alarm_tasks: dict[int, asyncio.Task] = {}
        self._next_alarm_id = 1

    async def initialize(self):
        """插件加载后初始化：准备数据目录并恢复未到期的闹钟。"""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"无法创建数据目录 {self._data_dir}：{e}")
        self._restore_alarms()
        logger.info(f"额外命令插件加载成功，数据目录：{self._data_dir}")

    async def terminate(self):
        """插件卸载/停用前取消所有后台闹钟任务。"""
        for task in self._alarm_tasks.values():
            if not task.done():
                task.cancel()
        self._alarm_tasks.clear()

    # ==================== 通用工具 ====================

    @staticmethod
    def _split_args(message_str: str) -> list[str]:
        """按空白切分消息并去掉指令本身，返回参数列表。"""
        return message_str.strip().split()[1:]

    @staticmethod
    def _parse_args(message_str: str, range: tuple[int, int]) -> list[str]:
        """解析参数。需要传入参数数量范围，如(0,2)。若参数数量不符合范围则抛出异常。"""
        args = ExtraCommands._split_args(message_str)
        args_count = len(args)

        if args_count < range[0]:  # 参数不足
            raise TooFewArgsError(args_count, range[0])
        elif args_count > range[1]:  # 参数过多
            raise TooManyArgsError(args_count, range[1])
        else:  # 参数数量符合范围
            return args

    @staticmethod
    def _require_min(args: list[str], least: int) -> None:
        """参数至少需要 least 个，否则抛出「参数不足」。"""
        if len(args) < least:
            raise TooFewArgsError(len(args), least)

    # ==================== 帮助指令 ====================

    @filter.command("ehelp", alias={"ext", "help"})
    @_args_error_to_reply("ehelp")
    async def ehelp(self, event: AstrMessageEvent):
        """显示插件总览帮助，或查看指定命令的帮助信息"""
        logger.info(event.get_messages())

        target = self._parse_args(event.message_str, (0, 1))
        if not target:  # 无参数或 ext：输出总览
            yield event.plain_result(EHELP_TEXT)
            return
        else:  # 有参数：输出指定命令的帮助
            help_text = get_help_text(target[0])
            yield event.plain_result(
                help_text if help_text is not None else not_found_text(target[0])
            )

    # ==================== /data 数据管理 ====================

    def _read_data(self) -> dict[str, str]:
        """读取键值数据：键值统一转成字符串，文件损坏时返回空表。"""
        payload = _load_json(self._data_path, {})
        if not isinstance(payload, dict):
            logger.warning("data.json 内容不是对象，已忽略")
            return {}
        return {str(k): str(v) for k, v in payload.items()}

    @staticmethod
    def _format_data_list(store: dict[str, str]) -> str:
        """数据总览文案。"""
        if not store:
            return "📭 暂无数据，可用 /data set [key] [value] 新建。"
        lines = [f"🗂 共 {len(store)} 条数据（上限 {DATA_MAX_KEYS}）："]
        lines.extend(f"· {key} = {_truncate(value, 40)}" for key, value in store.items())
        return "\n".join(lines)

    @filter.command("data")
    @_args_error_to_reply("data")
    async def data(self, event: AstrMessageEvent):
        """管理键值数据：get / set / del / mod"""
        args = self._split_args(event.message_str)
        action = args[0].lower() if args else "list"
        rest = args[1:]

        if action in ("ls", "list"):
            if rest:
                raise TooManyArgsError(len(rest), 0)
            async with self._data_lock:
                store = self._read_data()
            yield event.plain_result(self._format_data_list(store))
            return

        if action == "get":
            if not rest:  # /data get：等价于列出全部
                async with self._data_lock:
                    store = self._read_data()
                yield event.plain_result(self._format_data_list(store))
                return
            if len(rest) > 1:
                raise TooManyArgsError(len(rest), 1)
            key = rest[0]
            async with self._data_lock:
                store = self._read_data()
            if key not in store:
                yield event.plain_result(f"❌ 键「{key}」不存在。")
                return
            yield event.plain_result(f"📖 {key} = {store[key]}")
            return

        if action not in ("set", "del", "mod"):
            yield event.plain_result(
                f"❌ 未知子指令「{action}」。\n{get_help_text('data')}"
            )
            return

        if not event.is_admin():  # 写操作限管理员
            yield event.plain_result(ADMIN_ONLY)
            return

        self._require_min(rest, 1)
        key = rest[0]
        if not key or len(key) > DATA_MAX_KEY_LEN:
            yield event.plain_result(
                f"❌ 键名不能为空且不超过 {DATA_MAX_KEY_LEN} 个字符。"
            )
            return

        if action == "del":
            if len(rest) > 1:
                raise TooManyArgsError(len(rest), 1)
            async with self._data_lock:
                store = self._read_data()
                if key in store:
                    del store[key]
                    _save_json(self._data_path, store)
                    reply = f"🗑 已删除「{key}」。"
                else:
                    reply = f"❌ 键「{key}」不存在。"
            yield event.plain_result(reply)
            return

        self._require_min(rest, 2)
        value = " ".join(rest[1:])  # 值允许带空格
        if len(value) > DATA_MAX_VALUE_LEN:
            yield event.plain_result(f"❌ 值不超过 {DATA_MAX_VALUE_LEN} 个字符。")
            return

        async with self._data_lock:
            store = self._read_data()
            exists = key in store
            if action == "set" and exists:
                reply = f"❌ 键「{key}」已存在，如需修改请用 /data mod {key} [value]。"
            elif action == "mod" and not exists:
                reply = f"❌ 键「{key}」不存在，如需新建请用 /data set {key} [value]。"
            elif not exists and len(store) >= DATA_MAX_KEYS:
                reply = f"❌ 数据条目已达上限（{DATA_MAX_KEYS}）。"
            else:
                store[key] = value
                _save_json(self._data_path, store)
                verb = "新建" if action == "set" else "修改"
                reply = f"✅ 已{verb}「{key}」= {_truncate(value, 60)}"
        yield event.plain_result(reply)

    # ==================== /rand 随机数 ====================

    @filter.command("rand", alias={"random"})
    @_args_error_to_reply("rand")
    async def rand(self, event: AstrMessageEvent):
        """生成随机数：/rand [min] [max] [count]"""
        args = self._parse_args(event.message_str, (0, 3))
        try:
            numbers = [int(arg) for arg in args]
        except ValueError:
            yield event.plain_result(f"❌ 参数需为整数。\n{get_help_text('rand')}")
            return

        low, high = RAND_DEFAULT_RANGE
        count = 1
        if len(numbers) == 1:  # 只给一个数时视为 max
            low, high = 0, numbers[0]
        elif len(numbers) >= 2:
            low, high = numbers[0], numbers[1]
        if len(numbers) == 3:
            count = numbers[2]

        if low >= high:
            yield event.plain_result(f"❌ 需要 min < max（当前 {low} 与 {high}）。")
            return
        if not 1 <= count <= RAND_MAX_COUNT:
            yield event.plain_result(f"❌ 生成数量需在 1~{RAND_MAX_COUNT} 之间。")
            return

        drawn = [random.randint(low, high) for _ in range(count)]
        if count == 1:
            yield event.plain_result(f"🎲 随机数（{low}~{high}）：{drawn[0]}")
            return
        yield event.plain_result(
            f"🎲 随机数（{low}~{high}，共 {count} 个）："
            + "、".join(str(n) for n in drawn)
        )

    # ==================== /time 当前时间 ====================

    @filter.command("time")
    @_args_error_to_reply("time")
    async def time(self, event: AstrMessageEvent):
        """显示当前时间"""
        self._parse_args(event.message_str, (0, 0))  # 该指令不接受参数
        now = _beijing_now()
        weekday = "一二三四五六日"[now.weekday()]
        yield event.plain_result(
            f"🕒 当前时间：{now:%Y-%m-%d %H:%M:%S}（UTC+8 星期{weekday}）\n"
            f"🔢 Unix 时间戳：{int(now.timestamp())}"
        )

    # ==================== /alarm 闹钟 ====================

    def _load_alarms(self) -> None:
        """从磁盘载入闹钟记录。"""
        payload = _load_json(self._alarm_path, {"next_id": 1, "items": []})
        if not isinstance(payload, dict):
            logger.warning("alarms.json 内容异常，已忽略")
            payload = {}
        items = payload.get("items")
        self._alarms = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                alarm_id = int(item["id"])
                ts = float(item["ts"])
            except (KeyError, TypeError, ValueError):
                continue
            item["id"], item["ts"] = alarm_id, ts
            self._alarms[alarm_id] = item

        next_id = payload.get("next_id")
        self._next_alarm_id = next_id if isinstance(next_id, int) and next_id > 0 else 1
        for alarm_id in self._alarms:
            self._next_alarm_id = max(self._next_alarm_id, alarm_id + 1)

    def _persist_alarms(self) -> None:
        """把当前闹钟写回磁盘。"""
        _save_json(
            self._alarm_path,
            {"next_id": self._next_alarm_id, "items": list(self._alarms.values())},
        )

    def _restore_alarms(self) -> None:
        """载入磁盘闹钟并重建等待任务。"""
        self._load_alarms()
        for record in list(self._alarms.values()):
            self._schedule_alarm(record)
        if self._alarms:
            logger.info(f"额外命令插件恢复了 {len(self._alarms)} 个闹钟")

    def _schedule_alarm(self, record: dict[str, Any]) -> None:
        """为一条闹钟记录建立后台等待任务（同 id 的旧任务先取消）。"""
        old_task = self._alarm_tasks.get(record["id"])
        if old_task is not None and not old_task.done():
            old_task.cancel()
        self._alarm_tasks[record["id"]] = asyncio.create_task(self._wait_alarm(record))

    async def _wait_alarm(self, record: dict[str, Any]) -> None:
        """等待到点后发送提醒并清理记录。"""
        try:
            await asyncio.sleep(max(0.0, record["ts"] - time.time()))
            self._alarms.pop(record["id"], None)
            self._alarm_tasks.pop(record["id"], None)
            self._persist_alarms()
            await self._send_alarm(record)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 后台任务边界，任何异常都需记录而非崩溃
            logger.error("闹钟任务异常", exc_info=(type(e), e, e.__traceback__))

    async def _send_alarm(self, record: dict[str, Any]) -> None:
        """发送闹钟提醒。"""
        text = f"⏰ 闹钟到点啦（#{record['id']}）：{record.get('desc', '')}"
        if record.get("creator"):
            text += f"\n—— {record['creator']} 于 {_format_ts(record.get('created', 0))} 设置"
        try:
            await self.context.send_message(
                record["umo"], MessageChain([Comp.Plain(text)])
            )
        except Exception as e:  # noqa: BLE001 - 发送失败不应影响插件运行
            logger.error("闹钟提醒发送失败", exc_info=(type(e), e, e.__traceback__))

    def _format_alarm_list(self, event: AstrMessageEvent) -> str:
        """列出当前会话待触发的闹钟。"""
        session = event.get_session_id()
        items = sorted(
            (r for r in self._alarms.values() if r.get("session") == session),
            key=lambda r: r["ts"],
        )
        if not items:
            return "📭 当前没有待触发的闹钟，可用 /alarm set [timestamp] [desc] 设置。"
        lines = [f"⏰ 本会话待触发闹钟（{len(items)} 个，上限 {ALARM_PER_SESSION}）："]
        lines.extend(
            f"#{record['id']} {_format_ts(record['ts'])} · {record.get('desc', '')}"
            for record in items
        )
        return "\n".join(lines)

    def _add_alarm(self, event: AstrMessageEvent, ts: float, desc: str) -> str:
        """登记并持久化一个闹钟，返回回复文案。"""
        session = event.get_session_id()
        mine = [r for r in self._alarms.values() if r.get("session") == session]
        if len(mine) >= ALARM_PER_SESSION:
            return (
                f"❌ 本会话已有 {ALARM_PER_SESSION} 个闹钟，请先用 /alarm del [id] 取消。"
            )
        if len(self._alarms) >= ALARM_MAX_TOTAL:
            return f"❌ 闹钟总数已达上限（{ALARM_MAX_TOTAL}）。"

        record: dict[str, Any] = {
            "id": self._next_alarm_id,
            "ts": ts,
            "desc": desc,
            "umo": event.unified_msg_origin,
            "session": session,
            "creator": event.get_sender_name() or event.get_sender_id(),
            "created": time.time(),
        }
        self._next_alarm_id += 1
        self._alarms[record["id"]] = record
        self._persist_alarms()
        self._schedule_alarm(record)
        return (
            f"⏰ 闹钟已设置（#{record['id']}）\n"
            f"时间：{_format_ts(ts)}（{_format_duration(ts - time.time())}后）\n"
            f"描述：{desc}"
        )

    def _cancel_alarm(self, event: AstrMessageEvent, alarm_id: int) -> str:
        """取消指定闹钟，返回回复文案。"""
        record = self._alarms.get(alarm_id)
        if record is None:
            return f"❌ 没有编号为 #{alarm_id} 的闹钟。"
        if record.get("session") != event.get_session_id() and not event.is_admin():
            return "❌ 只能取消本会话设置的闹钟。"

        self._alarms.pop(alarm_id, None)
        task = self._alarm_tasks.pop(alarm_id, None)
        if task is not None and not task.done():
            task.cancel()
        self._persist_alarms()
        return f"🗑 已取消闹钟 #{alarm_id}（{record.get('desc', '')}）。"

    @filter.command("alarm")
    @_args_error_to_reply("alarm")
    async def alarm(self, event: AstrMessageEvent):
        """设置闹钟：/alarm set [timestamp] [desc]"""
        args = self._split_args(event.message_str)
        action = args[0].lower() if args else "list"
        rest = args[1:]

        if action in ("ls", "list"):
            if rest:
                raise TooManyArgsError(len(rest), 0)
            yield event.plain_result(self._format_alarm_list(event))
            return

        if action == "set":
            self._require_min(rest, 2)
            ts = _parse_alarm_time(rest[0])
            if ts is None:
                yield event.plain_result(
                    f"❌ 无法识别时间「{rest[0]}」。\n{get_help_text('alarm')}"
                )
                return
            if ts <= time.time():
                yield event.plain_result("❌ 该时间已经过去，请填一个将来的时间。")
                return
            desc = " ".join(rest[1:])
            if len(desc) > DATA_MAX_VALUE_LEN:
                yield event.plain_result(f"❌ 描述不超过 {DATA_MAX_VALUE_LEN} 个字符。")
                return
            yield event.plain_result(self._add_alarm(event, ts, desc))
            return

        if action in ("del", "delete", "rm", "cancel"):
            self._require_min(rest, 1)
            if len(rest) > 1:
                raise TooManyArgsError(len(rest), 1)
            raw_id = rest[0].lstrip("#")
            if not raw_id.isdigit():
                yield event.plain_result(
                    f"❌ 闹钟编号需为数字，例如 /alarm del 1。\n{get_help_text('alarm')}"
                )
                return
            yield event.plain_result(self._cancel_alarm(event, int(raw_id)))
            return

        yield event.plain_result(f"❌ 未知子指令「{action}」。\n{get_help_text('alarm')}")

    # ==================== /forcequit 退出机器人 ====================

    @filter.command("forcequit")
    @_args_error_to_reply("forcequit")
    async def forcequit(self, event: AstrMessageEvent):
        """退出机器人进程（仅管理员）"""
        if not event.is_admin():
            yield event.plain_result(ADMIN_ONLY)
            return
        self._parse_args(event.message_str, (0, 0))  # 该指令不接受参数

        logger.warning(
            f"收到 /forcequit：{event.get_sender_name()} 请求退出 AstrBot 进程"
        )
        yield event.plain_result("⚠️ 正在退出 AstrBot，请稍候…")
        asyncio.create_task(_quit_process())  # 让回复先送达，再退出

    # ==================== /log 查看日志 ====================

    @filter.command("log")
    @_args_error_to_reply("log")
    async def log(self, event: AstrMessageEvent):
        """查看最近日志（仅管理员，默认 10 条）"""
        if not event.is_admin():
            yield event.plain_result(ADMIN_ONLY)
            return

        args = self._parse_args(event.message_str, (0, 1))
        count = LOG_DEFAULT_COUNT
        if args:
            if not args[0].isdigit() or int(args[0]) <= 0:
                yield event.plain_result(f"❌ 参数需为正整数。\n{get_help_text('log')}")
                return
            count = min(int(args[0]), LOG_MAX_COUNT)

        lines = _recent_logs(count)
        if not lines:
            yield event.plain_result(
                "📭 暂无可读日志（内存缓存为空，且未启用日志文件）。"
            )
            return

        body = "\n".join(lines)
        if len(body) > LOG_MAX_CHARS:  # 只保留最新的部分
            body = "…（已截断）\n" + body[-LOG_MAX_CHARS:]
        yield event.plain_result(f"📜 最近 {len(lines)} 条日志：\n{body}")
