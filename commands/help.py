"""/help：显示插件总览帮助。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.help_text import EHELP_TEXT


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """在官方文档后显示插件总览帮助（所有人可用）。"""
    return event.plain_result(EHELP_TEXT)
