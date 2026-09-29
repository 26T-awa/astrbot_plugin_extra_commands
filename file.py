"""
文件操作模块
"""
import json
from pathlib import Path

PLUGIN_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugin_data"
    / "astrbot_plugin_extra_commands"
)
LEVEL_FILE = PLUGIN_DATA_DIR / "usergroup.json"
TIME_FILE = PLUGIN_DATA_DIR / "time.json"

def ensure_plugin_data_dir_exists():
    """确保插件数据目录存在。"""
    PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEVEL_FILE.touch(exist_ok=True)
    TIME_FILE.touch(exist_ok=True)

def _load_file(path: Path) -> dict:
    """从指定路径加载 JSON 数据，若文件不存在或内容为空则返回空字典。"""
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content) if content else {}
    except (json.JSONDecodeError, OSError):
        return {}

def _save_file(path: Path, data: dict) -> bool:
    """将数据保存为 JSON 文件，返回是否成功。"""
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        return True
    except OSError:
        return False