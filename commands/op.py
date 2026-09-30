"""/op：查看管理员列表、认领 owner、添加管理员。"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_target_id, split_args
from ..core.level import Level
from ..core.permissions import ensure_level

WRITE_FAILED = "❌ 写入 usergroup.json 失败，请查看日志。"


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """无参数时认领 owner，`@某人` 时把对方加为管理员，`list` 查看管理员列表。"""
    sender_id = event.get_sender_id()
    args = split_args(event.message_str)

    if args and args[0].lower() == "list":  # 显示管理员列表
        admin_list = "、".join(Level.Admin_list) or "（空）"
        return event.plain_result(f"📋 管理员列表：{admin_list}")

    target_id = parse_target_id(event.message_str)
    if not target_id:  # 无目标：认领 owner
        if Level.Owner:
            return event.plain_result(f"⚠️ 已有 owner（{Level.Owner}），无法认领。")
        if not Level.set_level(sender_id, Level.OWNER, owner_command=True):
            return event.plain_result(WRITE_FAILED)
        return event.plain_result(f"👑 已认领 owner：{sender_id}")

    ensure_level(event, Level.OWNER)  # 添加管理员：仅 owner 可以操作
    if target_id == Level.Owner or target_id in Level.Admin_list:
        return event.plain_result(f"⚠️ {target_id} 已是 owner 或 管理员。")
    if not Level.set_level(target_id, Level.ADMIN):
        return event.plain_result(WRITE_FAILED)
    return event.plain_result(f"✅ 已添加管理员：{target_id}")
