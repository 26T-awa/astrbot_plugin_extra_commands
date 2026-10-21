"""/ban：拉黑用户、查看黑名单、解除拉黑（仅 AstrBot 管理员可用）。

管理员身份统一由 AstrBot 官方权限体系判定（`admins_id` / `event.is_admin()`）：
`/op`、`/deop` 由官方插件 `builtin_commands_extension` 维护，本插件不再自己发放
管理员。拉黑记录仍写在 `<数据目录>/usergroup.json`（等级 0 = `baned`），
真正「不再受理」由 `core/guard.py` 的全局拦截完成：

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


def _official_admin_ids(plugin, event: AstrMessageEvent) -> set[str]:
    """取 AstrBot 官方管理员名单：默认配置 + 当前会话配置的并集。"""
    ids: set[str] = set()
    getters = [lambda: plugin.context.get_config()]
    umo = getattr(event, "unified_msg_origin", "")
    if umo:
        getters.append(lambda: plugin.context.get_config(umo=umo))
    for get in getters:
        try:
            cfg = get()
            for item in cfg.get("admins_id") or []:
                ids.add(str(item))
        except Exception:  # noqa: BLE001 - 读不到配置就少保护一层，不影响拉黑
            continue
    return ids


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """按第 1 个参数分派：`list` 查名单、`del` 解除，其余按拉黑处理。"""
    ensure_level(event, Level.ADMIN)  # 三种操作都要求 AstrBot 管理员

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
    return event.plain_result(_ban(plugin, event, target_id))


def _ban(plugin, event: AstrMessageEvent, target_id: str) -> str:
    """把目标用户写成 BANED，返回给用户的提示。"""
    if target_id == str(event.get_sender_id()):
        return "⚠️ 不能把自己拉黑。"
    if Level.is_banned(target_id):
        return f"⚠️ {target_id} 已经在黑名单里了。"
    if target_id in _official_admin_ids(plugin, event):  # 官方管理员不可拉黑
        return f"⚠️ 不能拉黑 AstrBot 管理员：{target_id}"
    if not Level.set_level(target_id, Level.BANED):
        return WRITE_FAILED
    return f"🚫 已拉黑：{target_id}，之后不再受理其任何消息。"


def _unban(target_id: str) -> str:
    """把目标用户恢复成普通成员，返回给用户的提示。"""
    if not Level.is_banned(target_id):
        return f"⚠️ {target_id} 不在黑名单里。"
    if not Level.set_level(target_id, Level.MEMBER):
        return WRITE_FAILED
    return f"✅ 已解除拉黑：{target_id}，恢复为普通成员。"
