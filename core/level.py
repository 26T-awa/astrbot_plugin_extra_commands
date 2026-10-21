"""封禁名单（/ban）与旧等级文件兼容。

权限已经统一交给 AstrBot 官方管理员体系（`admins_id` / `event.is_admin()`），
本模块只保留 `/ban` 需要的封禁名单：等级 0 = `baned`，其余一律按普通成员处理。

名单仍存放在 `<数据目录>/usergroup.json`，保持旧文件可读：

    {"123456789": "baned", "987654321": "member"}

旧版写入的 owner(4) / admin(3) 记录在读取时按普通成员处理，不再具有权限含义。
"""

from .storage import LEVEL_FILE, load_json, save_json


class Level:
    """封禁名单。只区分「已拉黑」和「普通成员」。"""

    level_str = {"admin": 3, "member": 1, "baned": 0}
    level_num = {3: "admin", 1: "member", 0: "baned"}

    ADMIN = 3  # 兼容命令侧的「需要管理员」参数；实际判定见 core.permissions
    MEMBER = 1
    BANED = 0

    data: dict[str, int] = {}  # {用户 ID: 等级数字}，只存 baned / member

    @classmethod
    def load(cls) -> bool:
        """从 usergroup.json 读取名单，把旧版的 owner/admin 记录降级为普通成员。"""
        raw = load_json(LEVEL_FILE)
        data: dict[str, int] = {}
        for uid, raw_level in raw.items():
            data[str(uid)] = cls.BANED if cls._is_baned(raw_level) else cls.MEMBER
        cls.data = data
        return True

    @classmethod
    def id_of(cls, uid: object) -> int:
        """0 = 已拉黑，1 = 普通成员（管理员身份不再由这里判定）。"""
        uid = "" if uid is None else str(uid)
        return cls.data.get(uid, cls.MEMBER)

    @classmethod
    def is_banned(cls, uid: object) -> bool:
        """该用户是否在黑名单里。"""
        return cls.id_of(uid) == cls.BANED

    @classmethod
    def name_of(cls, uid: object) -> str:
        """返回 baned / member，仅用于展示。"""
        return cls.level_num.get(cls.id_of(uid), "member")

    @classmethod
    def set_level(cls, uid: object, new_level: int | str) -> bool:
        """修改某个用户的封禁状态并写盘；只接受 baned(0) / member(1)。"""
        level = cls._normalize(new_level)
        if level is None:
            return False
        data = dict(cls.data)
        data[str(uid)] = level
        if not save_json(LEVEL_FILE, data):
            return False  # 写盘失败时保持内存不变，避免内存与文件不一致
        cls.data = data
        return True

    @staticmethod
    def _is_baned(raw: object) -> bool:
        """旧文件里的等级值是否表示「已拉黑」。"""
        if isinstance(raw, bool):
            return False
        if isinstance(raw, int):
            return raw == Level.BANED
        if isinstance(raw, str):
            return raw.strip().lower() in ("baned", "banned", "0")
        return False

    @staticmethod
    def _normalize(raw: object) -> int | None:
        """把等级值统一成 baned(0) / member(1)，认不出返回 None。"""
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw if raw in (Level.BANED, Level.MEMBER) else None
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text.isdigit():
                num = int(text)
                return num if num in (Level.BANED, Level.MEMBER) else None
            return {
                "baned": Level.BANED,
                "banned": Level.BANED,
                "member": Level.MEMBER,
            }.get(text)
        return None
