"""/deop：撤回管理员（owner 请直接编辑 usergroup.json）。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_target_id
from ..core.exceptions import TooFewArgsError
from ..core.level import Level
from ..core.permissions import ensure_level

WRITE_FAILED = "❌ 写入 usergroup.json 失败，请查看日志。"


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """`@某人` 时撤回对方的管理员身份（仅 owner 可以操作）。"""
    target_id = parse_target_id(event.message_str)
    if not target_id:
        raise TooFewArgsError(0, 1)

    ensure_level(event, Level.OWNER)
    if target_id not in Level.Admin_list:
        return event.plain_result(f"⚠️ {target_id} 不是管理员。")
    if not Level.set_level(target_id, Level.MEMBER):
        return event.plain_result(WRITE_FAILED)
    return event.plain_result(f"🗑️ 已撤回管理员：{target_id}")
