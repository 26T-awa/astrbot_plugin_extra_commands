"""AstrBot 额外命令插件。

本模块是插件入口：注册 Star 类、生命周期，以及每个命令的注册薄壳。
命令实现都在 `commands/` 包里，薄壳只做转发——AstrBot 依据
`handler.__module__` 把处理器绑定到插件实例上，所以 `@filter.command`
必须写在本模块内，不能下沉到子模块。
"""

from sys import maxsize

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star, register

from .commands import alarm as alarm_command
from .commands import ban as ban_command
from .commands import deop as deop_command
from .commands import edata as edata_command
from .commands import ehelp as ehelp_command
from .commands import forcequit as forcequit_command
from .commands import help as help_command
from .commands import log as log_command
from .commands import op as op_command
from .commands import rand as rand_command
from .commands import rc as rc_command
from .commands import time as time_command
from .core import guard
from .core import storage
from .core.handlers import catch_command_error
from .core.level import Level


@register("extra_commands", "_26T", "额外命令", "0.1")
class ExtraCommands(Star):
    """额外命令插件的主类。"""

    async def initialize(self):
        """插件实例化后由 AstrBot 自动调用。"""
        logger.info("额外命令插件加载成功")
        storage.ensure_data_dir()
        Level.load()
        await alarm_command.setup(self)  # 闹钟是 AstrBot 的定时任务，启动时重新绑好处理器
        await rc_command.setup(self)  # 概率回复：脚本掷骰，命中才叫一次模型，开关由 /rc 控制

    async def terminate(self):
        """插件被停用 / 卸载时由 AstrBot 调用。"""
        # 闹钟现在是 AstrBot 的定时任务，不随插件停用而消失；
        # 这里保留 basic 任务的处理器绑定，停用期间到点也还能把提醒发出去。
        logger.info("额外命令插件已停用，闹钟作为 AstrBot 定时任务继续保留")

    # ========== 全局拦截 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=maxsize)
    async def ban_guard(self, event: AstrMessageEvent):
        """最高优先级：黑名单用户的消息（聊天与指令）在受理前直接拦掉"""
        if guard.is_blocked(event):
            event.stop_event()

    # ========== 帮助 ==========

    @filter.command("help")
    @catch_command_error
    async def help(self, event: AstrMessageEvent):
        """在官方文档后显示插件总览帮助"""
        yield await help_command.run(self, event)

    @filter.command("ehelp", alias={"ext"})
    @catch_command_error
    async def ehelp(self, event: AstrMessageEvent):
        """显示插件总览帮助，或查看指定命令的帮助信息"""
        yield await ehelp_command.run(self, event)

    # ========== 实用命令 ==========

    @filter.command("edata", alias={"ed", "edt"})
    @catch_command_error
    async def edata(self, event: AstrMessageEvent):
        """管理插件数据"""
        yield await edata_command.run(self, event)

    @filter.command("rand", alias={"random"})
    @catch_command_error
    async def rand(self, event: AstrMessageEvent):
        """生成随机数"""
        yield await rand_command.run(self, event)

    @filter.command("time")
    @catch_command_error
    async def time(self, event: AstrMessageEvent):
        """显示时间"""
        yield await time_command.run(self, event)

    @filter.command("alarm")
    @catch_command_error
    async def alarm(self, event: AstrMessageEvent):
        """设置闹钟"""
        yield await alarm_command.run(self, event)

    @filter.command("rc", alias={"randomchat"})
    @catch_command_error
    async def rc(self, event: AstrMessageEvent):
        """开关概率回复：/rc on|off|status"""
        yield await rc_command.run(self, event)

    # ========== 权限与调试 ==========

    @filter.command("op")
    @catch_command_error
    async def op(self, event: AstrMessageEvent):
        """无参数：认领 owner；带用户 ID：添加管理员"""
        yield await op_command.run(self, event)

    @filter.command("deop")
    @catch_command_error
    async def deop(self, event: AstrMessageEvent):
        """撤回管理员（owner 请直接编辑 json文件）"""
        yield await deop_command.run(self, event)

    @filter.command("ban")
    @catch_command_error
    async def ban(self, event: AstrMessageEvent):
        """拉黑用户、查看黑名单、解除拉黑（owner / admin）"""
        yield await ban_command.run(self, event)

    @filter.command("log")
    @catch_command_error
    async def log(self, event: AstrMessageEvent):
        """查看最近的日志，交给模型分析并发一份文件（owner / admin）"""
        yield await log_command.run(self, event)

    @filter.command("forcequit", alias={"fq"})
    @catch_command_error
    async def forcequit(self, event: AstrMessageEvent):
        """退出机器人（owner / admin）"""
        yield await forcequit_command.run(self, event)
