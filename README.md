# astrbot-plugin-extra-commands

AstrBot 额外命令插件：随机数、时间查询、插件帮助、管理员（owner / admin）权限管理与进程退出。

> **现还处于测试阶段，功能不完善，欢迎大家提出建议**
>
> 其中 `/edata`、`/alarm`、`/log` 仍为**占位实现**，发送后会提示「尚未实现」并附上规划用法。

## 指令总览

| 指令 | 别名 | 参数 | 权限 | 状态 |
| -------------- | ------------ | ------------------------------------------ | ----------------- | -------- |
| `/help` | — | — | 所有人 | ✅ 可用 |
| `/ehelp` | `/ext` | `[command]` | 所有人 | ✅ 可用 |
| `/rand` | `/random` | `[-r <true\|false>] [min] [max] [count]` | 所有人 | ✅ 可用 |
| `/time` | — | — | 所有人 | ✅ 可用 |
| `/op` | — | `[@某人]` | 见「权限体系」 | ✅ 可用 |
| `/deop` | — | `@某人` | owner | ✅ 可用 |
| `/forcequit` | `/fq` | — | owner / admin | ✅ 可用 |
| `/edata` | — | `get` / `set` / `del` / `mod` | — | 🚧 占位 |
| `/alarm` | — | `set [timestamp] [desc]` | — | 🚧 占位 |
| `/log` | — | `[n]` | — | 🚧 占位 |

## `/rand` — 生成随机数

**位置参数 `[min] [max] [count]`**

- **至少要给一个数字**：`/rand` 不带数字会因「参数不足」中断，并且用户收不到回复（见「已知问题」）
- 只填一个数：视为 `max`，即 `0~max`
- 填两个数：`min max`
- 填三个数：`min max count`
- `count` 默认 1，上限 `RAND_MAX_COUNT = 100`
- 要求 `min ≤ max`；`min > max` 会报参数错误

**开关 `-r <true|false>`**

- 设置返回的随机数**是否允许重复**：`-r true`（默认）允许重复（逐个 `randint`）；`-r false` 不重复（`random.sample`），此时 `count` 不能超过区间内整数个数（`max - min + 1`）
- 该开关**只切换状态并回复提示，不会生成数字**，需要再发一次取值指令
- 状态保存在模块级全局变量 `RAND_REPEAT`：**对所有会话生效，且不落盘**（插件重载后回到默认 `true`）

```qq
/rand 10           0~10 取 1 个
/rand 1 10 3       1~10 取 3 个（允许重复）
/rand -r false     关闭重复开关
/rand 1 10 3       1~10 取 3 个不重复
```

## `/time` — 当前时间

回复北京时间的日期时间（含星期）与对应的 Unix 时间戳。

## `/ehelp`、`/help` — 帮助

- `/ehelp`（或 `/ext`）：输出插件总览
- `/ehelp <command>`：输出该指令的详细帮助，支持别名与 `/` 前缀（如 `/ehelp /random`）；命令不存在时提示改用 `/ehelp ext`
- `/help`：固定输出同一份总览

帮助文本集中在 `help_text.py`，是帮助内容的唯一数据源：

| 名字 | 说明 |
| -------------------- | --------------------------------------- |
| `EHELP_TEXT` | 总览帮助（`/ehelp`、`/help` 使用） |
| `HELP_TEXTS` | 每个指令各自的帮助文本，键为主指令名 |
| `ALIASES` | 主指令 → 别名，查询时归一处理 |
| `PENDING_COMMANDS` | 尚未实现的占位指令清单 |
| `get_help_text()` / `not_found_text()` / `pending_text()` | 查询与文案接口 |

## 权限体系（owner / admin / member）

等级保存在 `usergroup.json`，是一张「用户 ID → 等级」的映射：

```json
{
    "123456789": "owner",
    "987654321": "admin"
}
```

- **加载时机**：插件 `initialize()` 时读取一次；每次 `/op`、`/deop` 修改后立即重新读取
- **判定顺序**：`owner` → `admin` → `member`（`_get_level()`）
- `/op`（无参数）：认领 owner，仅当当前无 owner 时生效。⚠️ 该分支**没有权限校验**，谁先发谁就成为 owner，请部署后第一时间认领
- `/op @某人`：添加管理员，调用者须为 owner 或 admin。目标 ID 通过正则 `\((\d{5,})\)\s*$` 从消息**末尾**的 `@昵称(QQ号)` 中提取，因此必须真正 @ 对方（手打数字无效）
- `/deop @某人`：撤回管理员，调用者须为 owner；`owner` 无法用指令撤回，请直接编辑 `usergroup.json`
- `/forcequit`：须为 owner 或 admin，否则回复「权限越界！（需要 "admin"，实际上是 member）」

## 数据文件

均位于 `<AstrBot>/data/plugin_data/astrbot_plugin_extra_commands/`：

| 文件 | 用途 | 状态 |
| ---------------- | ---------------------------------- | -------- |
| `usergroup.json` | 用户等级 `{ID: owner/admin/member}` | ✅ 使用中 |
| `data.json` | `/edata` 的键值存储 | 🚧 预留 |
| `alarms.json` | `/alarm` 的闹钟记录 | 🚧 预留 |
| `time.json` | 时间相关数据 | 🚧 预留 |

路径由 `PLUGIN_DATA_DIR` 定义：插件目录的 `parents[2]`（即 AstrBot 的 `data/`）下的 `plugin_data/astrbot_plugin_extra_commands`。

## 安装

1. 把插件目录放到 AstrBot 的 `data/plugins/` 下，目录名为 `astrbot_plugin_extra_commands`
2. **手动创建数据目录** `data/plugin_data/astrbot_plugin_extra_commands/` —— 插件不会自动创建（见「已知问题」）
3. 重载插件，日志出现 `额外命令插件加载成功，占位指令：...` 即加载成功
4. 部署后由管理员先发一次 `/op` 认领 owner

无第三方依赖，仅使用 Python 标准库与 AstrBot 内置 API。

## 代码结构

| 文件 | 说明 |
| ----------------- | ------------------------------------------- |
| `main.py` | 插件主体：指令注册、参数解析、等级校验、延迟退出 |
| `help_text.py` | 帮助文本库（唯一数据源，不依赖 astrbot，可单独测试） |
| `exceptions.py` | 自定义异常：`ExtraCommandsError` 基类与参数/权限异常 |
| `metadata.yaml` | 插件元信息 |

- 指令统一用 `@filter.command(主指令, alias={别名...})` 注册，方法内 `yield` 回复
- 参数数量由静态方法 `_parse_args(message_str, (最小, 最大))` 统一校验
- `/forcequit` 的退出流程：先 `yield` 回复 → 后台任务等待 2 秒让消息送达 → `signal.raise_signal(SIGINT)` 走 AstrBot 正常退出流程 → 失败则 `os._exit(0)` 兜底

## 已知问题

- `/edata`、`/alarm`、`/log` 尚未实现
- 参数数量校验靠**抛异常**实现（`TooFewArgsError` / `TooManyArgsError` / `ArgsInputError`）。异常在 `yield` 生成器中抛出会直接中断该指令，**用户收不到回复**，只能从日志看到堆栈；例如 `/deop` 不给 @、`/rand` 不带数字都属于这种情况
- `/rand` 的帮助文本写着「默认范围 0~99，默认 1 个」，但实现要求至少 1 个数字（`_parse_args(..., (1, 3))`），因此 `RAND_DEFAULT_RANGE` 实际不会生效，无参数调用只会中断
- 数据目录不会自动创建；目录缺失时等级写盘会失败，但 `/op` 仍会回复「已添加管理员」
- `_get_level()` 使用 `id is OWNER` 比较字符串，改用 `==` 更可靠
- `/edata` 的占位提示调用 `pending_text("data")`，而帮助键名是 `edata`，因此提示中不会附带用法

## 许可证

GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。
