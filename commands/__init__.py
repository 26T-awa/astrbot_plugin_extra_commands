"""每个命令一个模块。

约定：命令模块提供 `async def run(plugin, event) -> MessageEventResult`，
返回本次要回复的内容；需要复用的能力放在 `core/` 里。`main.py` 只保留
`@filter.command` 注册薄壳——AstrBot 按 `handler.__module__` 把处理器绑定到
插件实例上，所以装饰器必须留在插件入口模块内。

命令模块：
- help / ehelp   帮助
- edata          数据管理（占位）
- rand           随机数
- time           时间与时区
- op / deop      owner 与管理员管理
- forcequit      退出 AstrBot 进程
- alarm          闹钟（登记为 AstrBot 定时任务）
- rc             概率回复开关
"""
