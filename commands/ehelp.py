"""/ehelp：显示插件总览帮助，或查看指定命令的帮助信息。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_args
from ..core.help_text import EHELP_TEXT, get_help_text, not_found_text


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """显示插件总览帮助，或查看指定命令的帮助信息（所有人可用）。"""
    args = parse_args(event.message_str, (0, 1))
    if not args:  # 无参数：输出总览
        return event.plain_result(EHELP_TEXT)

    command = args[0]  # 有参数：输出该命令的帮助，未知命令给出提示
    return event.plain_result(get_help_text(command) or not_found_text(command))
