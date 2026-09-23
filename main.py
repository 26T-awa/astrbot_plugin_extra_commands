import random
import re

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
    )

RAND_DEFAULT_RANGE = (0, 99)  # /rand 的默认范围
RAND_MAX_COUNT = 100  # /rand 的最大生成数量
RAND_REPEAT = True


@register("extra_commands", "_26T", "额外命令", "0.1")
class ExtraCommands(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info(f"额外命令插件加载成功，占位指令：{', '.join(PENDING_COMMANDS)}")

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

    @filter.command("data")
    async def data(self, event: AstrMessageEvent):
        """管理数据"""
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
            yield event.plain_result("⚠️ /rand -r true 已启用重复，若要关闭请使用 /rand -r false")
            RAND_REPEAT = True
            return
        elif flag.group(1).lower() == "false":
            yield event.plain_result("⚠️ /rand -r false 已关闭重复，若要开启请使用 /rand -r true")
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
            raise ArgsInputError(f"区间{low}>{high}",f"{low}<={high}", get_help_text("rand"))
        if not 1 <= count <= RAND_MAX_COUNT:
            raise ArgsInputError(f"数值{count}∉[1, {RAND_MAX_COUNT}]",f"{count}∈[1, {RAND_MAX_COUNT}]", get_help_text("rand"))
        if not RAND_REPEAT and count > minus:
            raise ArgsInputError(f"数值{count}∉[1, {minus}]",f"{count}∈[1, {minus}]", get_help_text("rand"))

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
        yield event.plain_result(pending_text("time"))

    @filter.command("alarm")
    async def alarm(self, event: AstrMessageEvent):
        """设置闹钟"""
        yield event.plain_result(pending_text("alarm"))

    @filter.command("forcequit")
    async def forcequit(self, event: AstrMessageEvent):
        """退出机器人"""
        yield event.plain_result(pending_text("forcequit"))

    @filter.command("log")
    async def log(self, event: AstrMessageEvent):
        """查看日志"""
        yield event.plain_result(pending_text("log"))

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
