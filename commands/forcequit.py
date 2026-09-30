"""/forcequit：退出 AstrBot 进程（owner / admin）。"""

import asyncio
import os
import signal

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.args import parse_args
from ..core.level import Level
from ..core.permissions import ensure_level

QUIT_DELAY = 2.0  # 延迟退出，留出时间让回复先送达
FORCE_QUIT_DELAY = 3.0  # 发出退出信号后再等一会，仍未退出则强制结束


async def run(plugin, event: AstrMessageEvent) -> MessageEventResult:
    """退出机器人（需 owner / admin）。"""
    ensure_level(event, Level.ADMIN)
    parse_args(event.message_str, (0, 0))  # 该指令不接受参数

    logger.warning(
        f"收到 /forcequit：{event.get_sender_name()}（{event.get_sender_id()}）"
        "请求退出 AstrBot 进程"
    )
    # 回复送达后再退出：_quit_process 会先等 QUIT_DELAY 秒
    asyncio.create_task(_quit_process())
    return event.plain_result("⚠️ 退出 AstrBot。")


async def _quit_process(delay: float = QUIT_DELAY) -> None:
    """延迟退出：先让回复消息送达，再触发 AstrBot 的退出流程。"""
    await asyncio.sleep(delay)
    logger.warning("额外命令插件执行 /forcequit，正在退出 AstrBot 进程")
    try:
        signal.raise_signal(signal.SIGINT)  # 优先走 AstrBot 的正常退出流程
        await asyncio.sleep(FORCE_QUIT_DELAY)
    except Exception as e:  # noqa: BLE001 - 非主线程等场景下退回强制退出
        logger.warning(f"发送退出信号失败，将强制退出：{e}")
    os._exit(0)
