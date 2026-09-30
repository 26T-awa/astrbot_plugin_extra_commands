"""插件的公共基础设施（与具体命令无关）。

- `storage`     数据目录与 JSON 读写
- `level`       用户权限等级（owner / admin / member / baned）
- `permissions` 命令权限校验
- `args`        命令参数解析
- `timeutil`    时间与时区工具（含闹钟时间解析）
- `cron`        AstrBot 定时任务的公共操作
- `handlers`    命令处理器适配（异常 → 回复）
- `exceptions`  自定义异常
- `help_text`   帮助文本库（纯数据，可单独导入测试）
"""
