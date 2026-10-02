"""/edata：管理每个用户的自定义数据。

数据以 JSON 存在 `<数据目录>/data.json`，按用户 ID 分组：

    {
        "2031915710": {"to_do_list": ["喝水"], "点数": 12},
        "123456789": {"nickname": "某人"}
    }

读写统一走 `core.storage`；默认操作发送者自己的数据，在消息末尾 `@某人`
（需要 admin）则操作对方的数据。参数里的 value 会先尝试当 JSON 解析，
解析不出来就原样存成字符串，所以 `1` 存成数字、`喝水` 存成字符串。
"""

import json
import re

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core import storage
from ..core.args import parse_target_id, split_args
from ..core.exceptions import ArgsInputError, TooFewArgsError, TooManyArgsError
from ..core.help_text import get_help_text
from ..core.level import Level
from ..core.permissions import ensure_level

DATA_FILE = storage.DATA_FILE
ACTIONS = ("get", "set", "append", "mod", "del", "keys", "clear")
WRITE_FAILED = "❌ 写入 data.json 失败，请查看日志。"


def _load() -> dict:
    """读取整张数据表；文件损坏时返回空表。"""
    return storage.load_json(DATA_FILE)


def _commit(data: dict, uid: str, bucket: dict) -> bool:
    """把某个用户的数据写回整表并落盘；数据空了就顺手把这个用户删掉。"""
    if bucket:
        data[uid] = bucket
    else:
        data.pop(uid, None)
    return storage.save_json(DATA_FILE, data)


def _strip_target(message_str: str) -> str:
    """去掉消息末尾的 `@昵称(QQ号)`，只留下指令与普通参数（昵称里的空格会污染 split）。"""
    return re.sub(r"@.*?\(\d{5,}\)\s*$", "", message_str).strip()


def _parse_value(text: str):
    """尽量把参数当 JSON 解析（数字 / 布尔 / 列表 / 对象），失败则原样存字符串。"""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _render(value) -> str:
    """把取出的值转成可读文本：字符串原样，其余用 JSON。"""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """增删改查用户自定义数据：/edata <get|set|append|mod|del|keys|clear> ..."""
    sender_id = str(event.get_sender_id())
    target_id = parse_target_id(event.message_str) or sender_id

    if target_id != sender_id:
        ensure_level(event, Level.ADMIN)  # 操作他人数据需要 admin
    else:
        ensure_level(event, Level.MEMBER)  # 自己的数据人人可管

    args = split_args(_strip_target(event.message_str))
    if not args:
        return event.plain_result(get_help_text("edata"))

    action = args[0].lower()
    if action not in ACTIONS:
        raise ArgsInputError(action, " / ".join(ACTIONS), get_help_text("edata"))
    params = args[1:]

    data = _load()
    bucket = data.get(target_id)
    if not isinstance(bucket, dict):
        bucket = {}

    # ---------------- 只读操作 ----------------
    if action == "get":
        if len(params) > 1:
            raise TooManyArgsError(len(params), 1)
        if not params:
            return event.plain_result(
                f"📄 {target_id} 的数据：\n"
                + (json.dumps(bucket, ensure_ascii=False, indent=2) if bucket else "（空）")
            )
        key = params[0]
        if key not in bucket:
            return event.plain_result(f"⚠️ 键「{key}」不存在。")
        return event.plain_result(f"📄 「{key}」= {_render(bucket[key])}")

    if action == "keys":
        if params:
            raise TooManyArgsError(len(params), 0)
        return event.plain_result(
            f"🔑 {target_id} 的键：{('、'.join(bucket) or '（空）')}"
        )

    # ---------------- 写操作 ----------------
    if action in ("set", "append", "mod"):
        if len(params) < 2:
            raise TooFewArgsError(len(params), 2)
        key = params[0]
        value = _parse_value(" ".join(params[1:]))

        if action == "append":
            current = bucket.get(key, [])
            if not isinstance(current, list):
                raise ArgsInputError(key, "列表类型的键", get_help_text("edata"))
            current.append(value)
            bucket[key] = current
        elif action == "mod":
            if key not in bucket:
                return event.plain_result(
                    f"⚠️ 键「{key}」不存在，无法修改（想新建请用 /edata set <key> <value>）。"
                )
            bucket[key] = value
        else:  # set：不存在则新建，存在则覆盖
            bucket[key] = value

        if not _commit(data, target_id, bucket):
            return event.plain_result(WRITE_FAILED)
        verb = {"set": "已设置", "append": "已追加", "mod": "已修改"}[action]
        return event.plain_result(f"✅ {verb}「{key}」= {_render(bucket[key])}")

    if action == "del":
        if len(params) < 1:
            raise TooFewArgsError(len(params), 1)
        if len(params) > 1:
            raise TooManyArgsError(len(params), 1)
        key = params[0]
        if key not in bucket:
            return event.plain_result(f"⚠️ 键「{key}」不存在。")
        del bucket[key]
        if not _commit(data, target_id, bucket):
            return event.plain_result(WRITE_FAILED)
        return event.plain_result(f"🗑️ 已删除「{key}」。")

    # action == "clear"
    if params:
        raise TooManyArgsError(len(params), 0)
    if not bucket:
        return event.plain_result(f"⚠️ {target_id} 的数据本来就是空的。")
    if not _commit(data, target_id, {}):
        return event.plain_result(WRITE_FAILED)
    return event.plain_result(f"🧹 已清空 {target_id} 的全部数据。")