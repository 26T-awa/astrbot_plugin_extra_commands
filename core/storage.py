"""插件数据目录与 JSON 读写。

数据统一放在 `<AstrBot>/data/plugin_data/<插件目录名>/` 下：本模块只负责路径
计算与读写，不参与任何命令逻辑，命令模块需要什么文件在这里登记常量即可。
"""

import json
from pathlib import Path

from astrbot.api import logger

PLUGIN_ROOT = Path(__file__).resolve().parents[1]  # 插件目录自身
DATA_ROOT = PLUGIN_ROOT.parents[1]  # <AstrBot>/data
PLUGIN_DATA_DIR = DATA_ROOT / "plugin_data" / PLUGIN_ROOT.name

LEVEL_FILE = PLUGIN_DATA_DIR / "usergroup.json"  # 用户权限等级表
DATA_FILE = PLUGIN_DATA_DIR / "data.json"  # /edata 的用户自定义数据
LEGACY_ALARM_FILE = PLUGIN_DATA_DIR / "alarms.json"  # 旧版闹钟记录（启动时迁移成定时任务）
LOG_DIR = PLUGIN_DATA_DIR / "logs"  # /log 导出的日志文件


def ensure_data_dir() -> bool:
    """确保插件数据目录存在，返回目录是否可用。"""
    try:
        PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"创建插件数据目录 {PLUGIN_DATA_DIR} 失败：{e}")
        return False
    return True


def write_log_file(name: str, text: str) -> Path | None:
    """把导出的日志写到 `LOG_DIR/name`，返回文件路径；写入失败返回 None。"""
    path = LOG_DIR / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        logger.error(f"写入日志文件 {name} 失败：{e}")
        return None
    return path


def load_json(path: Path) -> dict:
    """读取 JSON 对象；文件不存在、内容为空或格式损坏时返回空字典。"""
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content) if content.strip() else {}
    except OSError as e:
        logger.error(f"读取 {path.name} 失败：{e}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"{path.name} 不是合法的 JSON（{e}），已按空数据处理")
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict) -> bool:
    """把字典写成 JSON 文件（先写临时文件再替换，避免中途失败写坏原文件）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as e:
        logger.error(f"写入 {path.name} 失败：{e}")
        return False
    return True
