"""/edata：管理插件数据（占位实现）。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.help_text import pending_text
from ..core.level import Level
from ..core.permissions import ensure_level


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """管理插件数据（尚未实现，仅回复规划用法；需 admin）。"""
    ensure_level(event, Level.ADMIN)
    return event.plain_result(pending_text("edata"))
