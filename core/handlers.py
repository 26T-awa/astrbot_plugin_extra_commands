"""命令处理器的适配层。

AstrBot 按 `handler.__module__` 把命令挂到插件上，并给处理器注入插件实例，
所以 `@filter.command` 必须写在插件入口 `main.py` 里；命令实现放在
`commands/` 包中，由这里统一转发和兜底。
"""

import functools

from .exceptions import ExtraCommandsError


def catch_command_error(method):
    """把命令抛出的 ExtraCommandsError 转成给用户的回复。

    参数不足、参数格式错误、权限不足等都以异常的形式抛出；AstrBot 只会在
    日志里记录异常，用户收不到任何反馈，所以统一在这里接住并回复。
    """

    @functools.wraps(method)
    async def wrapper(self, event):
        try:
            async for result in method(self, event):
                yield result
        except ExtraCommandsError as e:
            yield event.plain_result(str(e))

    return wrapper
