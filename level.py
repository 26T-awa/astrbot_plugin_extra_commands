"""
权限等级管理模块
"""

from file import (
    LEVEL_FILE,
    ensure_plugin_data_dir_exists,
    _load_file,
    _save_file,
)

class Level:
    level_str = {
        "owner": 4,
        "admin": 3,
        "member": 1,
        "baned": 0,
    }  # 权限等级列表，按优先级从高到低排列
    level_num = {
        4: "owner",
        3: "admin",
        1: "member",
        0: "baned",
    }
    Owner = ""
    Admin_list = []
    data = {}  # 存储权限等级数据的字典

    @staticmethod
    def _get_level_id(id: str) -> int:
        """返回ID的权限数字等级：4/3/1"""
        if id is Level.Owner:
            return 4
        elif id in Level.Admin_list:
            return 3
        else:
            return 1

    @staticmethod
    def _level_check(sender_id: str, required_level: int) -> bool:
        """检查用户权限等级。返回 True 表示有权限，False 表示无权限。"""
        level_id = Level._get_level_id(sender_id)
        return level_id >= required_level

    @staticmethod
    def _load_levelfile() -> bool:
        """加载权限等级文件，更新 OWNER 和 ADMIN_LIST。返回是否成功。"""
        Level.data = _load_file(LEVEL_FILE)  # 确保文件存在
        Level.Owner = next((k for k, v in Level.data.items() if v == "owner"), "")
        Level.Admin_list = [k for k, v in Level.data.items() if v == "admin"]
        return True

    @staticmethod
    def _mdf_level(id: str, newlevel: int, ownercommand: bool = False) -> bool:
        """修改用户权限等级。若 id 为 owner 则必须 ownercommand 为 True 才能修改。"""
        if newlevel not in Level.level_num:
            return False  # 无效等级
        if id == Level.Owner and not ownercommand:
            return False  # 不允许修改 owner 的权限，除非是 owner 自己操作

        Level.data[id] = newlevel
        success = _save_file(LEVEL_FILE, Level.data)
        if success: # 更新 Owner 和 Admin_list
            Level.Owner = next((k for k, v in Level.data.items() if v == "owner"), "")
            Level.Admin_list = [k for k, v in Level.data.items() if v == "admin"]
        return success
