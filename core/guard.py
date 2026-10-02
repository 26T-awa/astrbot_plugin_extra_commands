"""全局拦截：黑名单用户的消息一律不受理。

被拉黑的用户等级为 `Level.BANED`（0）。`main.py` 以**全类型 + 最高优先级**
把这个判定注册成处理器，它会在其它所有处理器之前跑：命中黑名单就
`event.stop_event()`，把事件在管线这一层直接掐掉——日常聊天和指令都不再
往下走，模型也不会被叫起来。

判定逻辑独立在这里，是为了让 `main.py` 只留一层薄薄的注册壳。
"""

from astrbot.api.event import AstrMessageEvent

from .level import Level


def is_blocked(event: AstrMessageEvent) -> bool:
    """该事件的发送者是否在黑名单里。取不到发送者时按放行处理，避免误伤。"""
    try:
        return Level.id_of(event.get_sender_id()) == Level.BANED
    except Exception:
        return False
