"""/ban：拉黑用户、查看黑名单、解除拉黑（仅 owner / admin 可用）。

拉黑就是把人降到 `Level.BANED`（等级 0），等级表与等级判定都由
`core/level.py` 负责，本模块只做参数解析与结果回复：

    /ban @<user>    拉黑，之后不再受理其任何消息（含指令）
    /ban list       查看黑名单
    /ban del @<user> 解除拉黑，恢复成普通成员
"""

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_target_id, split_args
from ..core.exceptions import ArgsInputError, TooFewArgsError
from ..core.level import Level
from ..core.permissions import ensure_level

WRITE_FAILED = "❌ 写入 usergroup.json 失败，请查看日志。"
UNKNOWN_ARG = "list / del @<user> / @<user>"


def _banned_ids() -> list[str]:
    """黑名单里的用户 ID（等级为 BANED 的记录）。"""
    return [uid for uid, level in Level.data.items() if level == Level.BANED]


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """按第 1 个参数分派：`list` 查名单、`del` 解除，其余按拉黑处理。"""
    ensure_level(event, Level.ADMIN)  # 三种操作都要求 owner 或 admin

    args = split_args(event.message_str)
    if not args:  # 既没有目标也没有子命令
        raise TooFewArgsError(0, 1)

    if args[0].lower() == "list":  # 查名单不需要目标用户
        banned = "、".join(_banned_ids()) or "（空）"
        return event.plain_result(f"🚫 黑名单：{banned}")

    is_del = args[0].lower() == "del"
    target_id = parse_target_id(event.message_str)
    if not target_id:
        # `/ban del` 缺目标按参数不足报，其余情况是首参数认不出
        raise TooFewArgsError(1, 2) if is_del else ArgsInputError(
            args[0], UNKNOWN_ARG
        )

    if is_del:
        return event.plain_result(_unban(target_id))
    return event.plain_result(_ban(event.get_sender_id(), target_id))


def _ban(sender_id: str, target_id: str) -> str:
    """把目标用户写成 BANED，返回给用户的提示。"""
    if target_id == str(sender_id):
        return "⚠️ 不能把自己拉黑。"
    if Level.id_of(target_id) == Level.BANED:
        return f"⚠️ {target_id} 已经在黑名单里了。"
    if Level.check(target_id, Level.ADMIN):  # owner / admin 不在可拉黑范围内
        return f"⚠️ 不能拉黑 owner 或 管理员：{target_id}"
    if not Level.set_level(target_id, Level.BANED):
        return WRITE_FAILED
    return f"🚫 已拉黑：{target_id}，之后不再受理其任何消息。"


def _unban(target_id: str) -> str:
    """把目标用户恢复成普通成员，返回给用户的提示。"""
    if Level.id_of(target_id) != Level.BANED:
        return f"⚠️ {target_id} 不在黑名单里。"
    if not Level.set_level(target_id, Level.MEMBER):
        return WRITE_FAILED
    return f"✅ 已解除拉黑：{target_id}，恢复为普通成员。"
