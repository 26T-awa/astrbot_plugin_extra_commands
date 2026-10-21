"""命令的权限校验。

权限统一走 AstrBot 官方管理员体系：`admins_id` 里的用户由 AstrBot 在消息管线里
标记为管理员（`event.is_admin()`）；`/op`、`/deop` 由官方插件
`builtin_commands_extension` 维护，本插件不再自己维护管理员名单。
"""

from .exceptions import PermissionError
from .level import Level


def ensure_level(event, required_level: int) -> None:
    """要求消息发送者达到 `required_level`，否则抛出 PermissionError。

    - `Level.MEMBER`：所有未被拉黑的用户都能用（拉黑由 `core.guard` 全局拦截）；
    - `Level.ADMIN`：必须是 AstrBot 官方管理员（`event.is_admin()`）。
    """
    sender_id = event.get_sender_id()
    if required_level <= Level.MEMBER:
        return
    if event.is_admin():
        return
    raise PermissionError(Level.id_of(sender_id), required_level)
