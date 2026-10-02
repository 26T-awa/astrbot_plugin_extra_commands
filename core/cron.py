"""AstrBot 定时任务（cron）的公共操作。

闹钟（/alarm）与概率回复（/rc）都挂在 AstrBot 的定时任务上，这里放两者
共用的取值逻辑，避免每个命令各写一份。
"""

from typing import Any


def manager(plugin) -> Any:
    """取 AstrBot 的定时任务管理器；拿不到时返回 None。"""
    return getattr(plugin.context, "cron_manager", None)


def payload(job: Any) -> dict:
    """取定时任务的 payload；缺失或类型不对时返回空字典。"""
    value = getattr(job, "payload", None)
    return value if isinstance(value, dict) else {}


async def find_job(
    plugin, origin: str, session: str | None = None, job_type: str = "basic"
) -> Any:
    """按 payload 里的 origin 找一条定时任务；找不到时返回 None。

    传了 `session` 时只认 payload 里 umo/session 与之相符的那条，用于
    「一个会话一条任务」的场景（概率回复）。
    """
    cron_mgr = manager(plugin)
    if cron_mgr is None:
        return None
    for job in await cron_mgr.list_jobs(job_type):
        data = payload(job)
        if data.get("origin") != origin:
            continue
        if session is None or str(data.get("umo") or data.get("session") or "") == session:
            return job
    return None
