"""/ehelp：显示插件总览帮助、查看指定命令帮助，或发送「命令帮助手册.pdf」。

`/ehelp !` 会把手册作为文件发到当前私聊 / 群聊。手册放在插件数据目录里
（`<AstrBot>/data/plugin_data/astrbot_plugin_extra_commands/命令帮助手册.pdf`），
属于公共数据：插件代码更新时不会把它覆盖掉，想换内容直接替换文件即可。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import File, Plain

from ..core import storage
from ..core.args import parse_args
from ..core.help_text import (
    EHELP_TEXT,
    MANUAL_MISSING_TEXT,
    get_help_text,
    not_found_text,
)

# 命令帮助手册：放在插件数据目录，作为公共数据，插件更新不会覆盖
HELP_PDF = storage.PLUGIN_DATA_DIR / "命令帮助手册.pdf"
SEND_FLAGS = ("!", "！")  # 半角 / 全角感叹号都认，照顾中文输入法


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """显示总览、查看单个命令帮助，或用 `!` 把命令帮助手册发出来（所有人可用）。"""
    args = parse_args(event.message_str, (0, 1))
    if not args:  # 无参数：输出总览
        return event.plain_result(EHELP_TEXT)

    if args[0] in SEND_FLAGS:  # /ehelp !：把手册作为文件发到当前会话
        return _manual_result(event)

    command = args[0]  # 有参数：输出该命令的帮助，未知命令给出提示
    return event.plain_result(get_help_text(command) or not_found_text(command))


def _manual_result(event: AstrMessageEvent) -> MessageEventResult:
    """把命令帮助手册作为文件发出去；文件不存在时回复放置路径。"""
    if not HELP_PDF.is_file():
        return event.plain_result(MANUAL_MISSING_TEXT.format(path=HELP_PDF))

    logger.info(
        f"收到 /ehelp !：向 {event.unified_msg_origin} 发送命令帮助手册 {HELP_PDF.name}"
    )
    return event.chain_result(
        # 文件段在 aiocqhttp 上是单独一条消息，所以文本放前面、文件跟后面
        [
            Plain(f"📘 命令帮助手册（{HELP_PDF.name}）发给你了。"),
            File(name=HELP_PDF.name, file=str(HELP_PDF)),
        ]
    )
