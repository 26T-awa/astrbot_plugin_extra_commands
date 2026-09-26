import asyncio
import os
import random
import re
import signal
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

try:  # 以包形式加载时优先使用相对导入
    from .help_text import (  # 命令帮助文本
        EHELP_TEXT,
        PENDING_COMMANDS,
        get_help_text,
        not_found_text,
        pending_text,
    )
    from .exceptions import (  # 自定义异常
        TooManyArgsError,
        TooFewArgsError,
        ArgsInputError,
        PermissionError,
    )
except ImportError:  # 兜底：插件被当作顶层模块加载时
    from help_text import (  # 命令帮助文本
        EHELP_TEXT,
        PENDING_COMMANDS,
        get_help_text,
        not_found_text,
        pending_text,
    )
    from exceptions import (  # 自定义异常
        TooManyArgsError,
        TooFewArgsError,
        ArgsInputError,
        PermissionError,
    )

PLUGIN_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugin_data"
    / "astrbot_plugin_extra_commands"
)
LEVEL_FILE = PLUGIN_DATA_DIR / "usergroup.json"
TIME_FILE = PLUGIN_DATA_DIR / "time.json"

OWNER = ""
ADMIN_LIST = []

RAND_DEFAULT_RANGE = (0, 99)  # /rand 的默认范围
RAND_MAX_COUNT = 100  # /rand 的最大生成数量
RAND_REPEAT = True


@register("extra_commands", "_26T", "额外命令", "0.1")
class ExtraCommands(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._data_dir = PLUGIN_DATA_DIR
        self._data_path = self._data_dir / "data.json"
        self._alarm_path = self._data_dir / "alarms.json"
        self._time_path = self._data_dir / "time.json"
        self._level_path = self._data_dir / "usergroup.json"
        self._data_lock = asyncio.Lock()
        self._alarms: dict[int, dict[str, Any]] = {}
        self._alarm_tasks: dict[int, asyncio.Task] = {}
        self._next_alarm_id = 1


    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info(f"额外命令插件加载成功，占位指令：{', '.join(PENDING_COMMANDS)}")
        ExtraCommands._load_level()

    """
    静态方法列表
    """

    @staticmethod
    def _parse_args(message_str: str, range: tuple[int, int]) -> list[str]:
        """解析参数。需要传入参数数量范围，如(0,2)。若参数数量不符合范围则抛出异常。"""
        parts = message_str.strip().split()
        args_count = len(parts) - 1  # 去掉指令本身，参数数量

        if args_count < range[0]:  # 参数不足
            raise TooFewArgsError(args_count, range[0])
        elif args_count > range[1]:  # 参数过多
            raise TooManyArgsError(args_count, range[1])
        else:  # 参数数量符合范围
            parts = parts[1:]  # 去掉指令本身
            return parts

    @staticmethod
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

    @staticmethod
    def _load_level() -> bool:
        global OWNER
        global ADMIN_LIST
        if not LEVEL_FILE.exists():
            return False

        try:
            data = json.loads(LEVEL_FILE.read_text(encoding="utf-8"))
            OWNER = next((k for k, v in data.items() if v == "owner"), "")
            ADMIN_LIST = [k for k, v in data.items() if v == "admin"]
            return True
        except (json.JSONDecodeError, OSError):
            return False

    @staticmethod
    def _mdf_level(id: str, level: str, ownercommand: bool = False) -> bool:
        if LEVEL_FILE.exists():
            try:
                data = json.loads(LEVEL_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
        else:
            data = {}

        if ownercommand or (id != OWNER and level != "owner"):
            data[id] = level

        try:
            LEVEL_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
        except OSError:
            return False

        return ExtraCommands._load_level()

    @staticmethod
    def _get_level(id: str) -> str:
        if id is OWNER:
            return "owner"
        elif id in ADMIN_LIST:
            return "admin"
        else:
            return "member"

    """
    插件命令实现
    """

    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        """在官方文档后显示插件总览帮助"""
        yield event.plain_result(EHELP_TEXT)

    @filter.command("ehelp", alias={"ext"})
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

    @filter.command("edata")
    async def edata(self, event: AstrMessageEvent):
        """管理插件数据"""
        yield event.plain_result(pending_text("data"))

    @filter.command("rand", alias={"random"})
    async def rand(self, event: AstrMessageEvent):
        """生成随机数"""
        global RAND_REPEAT  # 允许重复的开关

        flag = re.search(r"-r\s+(\S+)", event.message_str, re.I)
        if not flag:
            args = self._parse_args(event.message_str, (1, 3))  # 最多 3 个数字
            if not args:
                raise TooFewArgsError(0, 1)
        elif flag.group(1).lower() == "true":
            yield event.plain_result(
                "⚠️ /rand -r true 已启用重复，若要关闭请使用 /rand -r false"
            )
            RAND_REPEAT = True
            return
        elif flag.group(1).lower() == "false":
            yield event.plain_result(
                "⚠️ /rand -r false 已关闭重复，若要开启请使用 /rand -r true"
            )
            RAND_REPEAT = False
            return
        else:
            raise ArgsInputError(flag.group(1), "true/false", get_help_text("rand"))

        # ---- 位置参数：min / max / count ----
        numbers = []
        for arg in args:
            try:
                numbers.append(int(arg))
            except ValueError:
                raise ArgsInputError(arg, "整数", get_help_text("rand"))

        low, high = RAND_DEFAULT_RANGE
        count = 1
        if len(numbers) == 1:  # 只给一个数时视为 max
            low, high = 0, numbers[0]
        elif len(numbers) >= 2:
            low, high = numbers[0], numbers[1]
        if len(numbers) == 3:
            count = numbers[2]

        minus = high - low + 1
        if minus <= 0:
            raise ArgsInputError(
                f"区间{low}>{high}", f"{low}<={high}", get_help_text("rand")
            )
        if not 1 <= count <= RAND_MAX_COUNT:
            raise ArgsInputError(
                f"数值{count}∉[1, {RAND_MAX_COUNT}]",
                f"{count}∈[1, {RAND_MAX_COUNT}]",
                get_help_text("rand"),
            )
        if not RAND_REPEAT and count > minus:
            raise ArgsInputError(
                f"数值{count}∉[1, {minus}]",
                f"{count}∈[1, {minus}]",
                get_help_text("rand"),
            )

        drawn = (
            [random.randint(low, high) for _ in range(count)]
            if RAND_REPEAT
            else random.sample(range(low, high + 1), count)
        )

        if count == 1:
            yield event.plain_result(f"🎲 随机数（{low}~{high}）：{drawn[0]}")
            return
        note = "" if RAND_REPEAT else "，不重复"
        yield event.plain_result(
            f"🎲 随机数（{low}~{high}，共 {count} 个{note}）："
            + "、".join(str(n) for n in drawn)
        )

    @filter.command("time")
    async def time(self, event: AstrMessageEvent):
        """显示时间"""
        now = datetime.now(timezone(timedelta(hours=8)))
        weekday = "一二三四五六日"[now.weekday()]
        yield event.plain_result(
            f"🕒 当前时间：{now:%Y-%m-%d %H:%M:%S}（UTC+8 星期{weekday}）\n"
            f"🔢 Unix 时间戳：{int(now.timestamp())}"
        )

    @filter.command("forcequit", alias={"fq"})
    async def forcequit(self, event: AstrMessageEvent):
        """退出机器人（owner / admin）"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()

        if senderid != OWNER and senderid not in ADMIN_LIST:
            yield event.plain_result(str(PermissionError(self._get_level(senderid))))
            return

        logger.warning(
            f"收到 /forcequit：{event.get_sender_name()}（{senderid}）请求退出 AstrBot 进程"
        )
        yield event.plain_result("⚠️ 退出 AstrBot。")
        asyncio.create_task(self._quit_process())  # 让回复先送达，再退出

    @filter.command("op")
    async def op(self, event: AstrMessageEvent):
        """无参数：认领 owner；带用户 ID：添加管理员"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()
        targetid = re.search(r"\((\d{5,})\)\s*$", event.message_str)
        if targetid:
            targetid = targetid.group(1)
        else:
            targetid = ""
        senderlevel = self._get_level(senderid)

        if targetid:
            if senderid != OWNER and senderid not in ADMIN_LIST:  # 带参数：添加管理员
                yield event.plain_result(str(PermissionError(senderlevel, "owner")))
                return

            elif targetid == OWNER or targetid in ADMIN_LIST:
                yield event.plain_result(f"⚠️ {targetid} 已是 owner 或 管理员。")
                return

            else:
                self._mdf_level(targetid, "admin")
            yield event.plain_result(f"✅ 已添加管理员：{targetid}")

        else:
            if OWNER:
                yield event.plain_result(f"⚠️ 已有 owner（{OWNER}），无法认领。")
                return

            else:
                self._mdf_level(senderid, "owner", True)
                yield event.plain_result(f"👑 已认领 owner：{senderid}")
                return

    @filter.command("deop")
    async def deop(self, event: AstrMessageEvent):
        """撤回管理员（owner 请直接编辑 json文件）"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()
        targetid = re.search(r"\((\d{5,})\)\s*$", event.message_str)
        if targetid:
            targetid = targetid.group(1)
        else:
            targetid = ""
        senderlevel = self._get_level(senderid)

        if targetid:

            if senderid != OWNER:  # 带参数：撤回管理员
                yield event.plain_result(str(PermissionError(senderlevel, "owner")))
                return

            elif targetid not in ADMIN_LIST:
                yield event.plain_result(f"⚠️ {targetid} 不是管理员。")
                return

            else:
                self._mdf_level(targetid, "member")
            yield event.plain_result(f"🗑️ 已撤回管理员：{targetid}")

        else:
            raise TooFewArgsError(0, 1)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
