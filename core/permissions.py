"""命令的权限校验。

所有命令都通过这里校验权限，避免每个命令各写一遍
「判等级 → 抛异常」的模板代码。
"""

from .exceptions import PermissionError
from .level import Level


def ensure_level(event, required_level: int) -> None:
    """要求消息发送者达到 `required_level`，否则抛出 PermissionError。"""
    sender_id = event.get_sender_id()
    if not Level.check(sender_id, required_level):
        raise PermissionError(Level.id_of(sender_id), required_level)
