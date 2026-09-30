"""用户权限等级管理（owner / admin / member / baned）。

等级表存放在 `<数据目录>/usergroup.json`：

    {"123456789": "owner", "987654321": "admin"}

插件启动时读一次；每次 /op、/deop 修改成功后立即写盘并刷新内存里的
`Owner` 与 `Admin_list`，所以判定等级时不需要反复读文件。
"""

from .storage import LEVEL_FILE, load_json, save_json


class Level:
    """权限等级表及其判定。等级数字越大权限越高。"""

    level_str = {"owner": 4, "admin": 3, "member": 1, "baned": 0}
    level_num = {4: "owner", 3: "admin", 1: "member", 0: "baned"}

    OWNER = 4
    ADMIN = 3
    MEMBER = 1
    BANED = 0

    Owner = ""  # 当前 owner 的用户 ID；空串表示还没有人认领
    Admin_list: list[str] = []  # 当前所有管理员的用户 ID
    data: dict[str, int] = {}  # {用户 ID: 等级数字}

    @classmethod
    def load(cls) -> bool:
        """从 usergroup.json 读取等级表并刷新 Owner / Admin_list。"""
        raw = load_json(LEVEL_FILE)
        data: dict[str, int] = {}
        for uid, raw_level in raw.items():
            level = cls._normalize(raw_level)
            if level is None:  # 认不出的等级按普通成员处理
                level = cls.MEMBER
            data[str(uid)] = level
        cls.data = data
        cls.refresh_roles()
        return True

    @classmethod
    def id_of(cls, uid: object) -> int:
        """返回用户 ID 对应的等级数字：4 / 3 / 1。"""
        uid = "" if uid is None else str(uid)  # 统一成字符串，避免类型不一致
        if cls.Owner and uid == cls.Owner:  # 用 == 比较，is 比的是对象身份
            return cls.OWNER
        if uid in cls.Admin_list:
            return cls.ADMIN
        return cls.MEMBER

    @classmethod
    def name_of(cls, uid: object) -> str:
        """返回用户 ID 对应的等级名：owner / admin / member / baned。"""
        return cls.level_num.get(cls.id_of(uid), "member")

    @classmethod
    def check(cls, sender_id: object, required_level: int) -> bool:
        """等级是否达到 required_level。"""
        return cls.id_of(sender_id) >= required_level

    @classmethod
    def refresh_roles(cls) -> None:
        """按 data 重新整理 Owner 与 Admin_list。"""
        cls.Owner = next(
            (uid for uid, level in cls.data.items() if level == cls.OWNER), ""
        )
        cls.Admin_list = [
            uid for uid, level in cls.data.items() if level == cls.ADMIN
        ]

    @classmethod
    def set_level(
        cls, uid: object, new_level: int | str, owner_command: bool = False
    ) -> bool:
        """修改用户等级并写盘。

        `owner_command` 为 True 时表示这次改动由 owner 发起（认领流程），
        否则不允许改写 owner 自己的等级。
        """
        level = cls._normalize(new_level)
        if level is None:
            return False
        uid = str(uid)
        if cls.Owner and uid == cls.Owner and not owner_command:
            return False

        data = dict(cls.data)
        data[uid] = level
        if not save_json(LEVEL_FILE, data):
            return False  # 写盘失败时保持内存不变，避免内存与文件不一致
        cls.data = data
        cls.refresh_roles()
        return True

    @staticmethod
    def _normalize(raw: object) -> int | None:
        """把等级值统一成数字。支持 4/3/1/0 或 owner/admin/member/baned，认不出返回 None。"""
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw if raw in Level.level_num else None
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text.isdigit():
                num = int(text)
                return num if num in Level.level_num else None
            return Level.level_str.get(text)
        return None
