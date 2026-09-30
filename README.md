# astrbot-plugin-extra-commands

AstrBot 额外命令插件：随机数、时间与时区、闹钟、概率回复、插件帮助，以及 owner / 管理员权限管理与进程退出。

> 作者：**26T-awa** · 版本：**v0.6** · [GitHub 仓库](https://github.com/26T-awa/astrbot_plugin_extra_commands)
>
> 其中 `/edata`、`/log`、`/ban` 仍为**占位实现**（`/log`、`/ban` 尚未注册），发送 `/edata` 会提示「尚未实现」并附上规划用法。

## 指令总览

| 指令 | 别名 | 参数 | 权限 | 状态 |
| ---------------- | ------------ | ------------------------------------------------- | ------------- | ------ |
| `/help` | — | — | 所有人 | ✅ 可用 |
| `/ehelp` | `/ext` | `[command]` | 所有人 | ✅ 可用 |
| `/rand` | `/random` | `[-r <true\|false>] [min] [max] [count]` | 所有人 | ✅ 可用 |
| `/time` | — | `[时区]`、`setzone <时区>` | 所有人 | ✅ 可用 |
| `/alarm` | — | `set <时间> <描述> [-llm]`、`list`、`del #<编号>` | 所有人 | ✅ 可用 |
| `/rc` | `/randomchat` | `on` / `off` / `status` | admin | ✅ 可用 |
| `/op` | — | 无参数认领 owner；`@某人` 加管理员；`list` 看列表 | 见「权限体系」 | ✅ 可用 |
| `/deop` | — | `@某人` | owner | ✅ 可用 |
| `/forcequit` | `/fq` | — | owner / admin | ✅ 可用 |
| `/edata` | — | `get` / `set` / `del` / `mod` | admin | 🚧 占位 |
| `/log` | — | `[n]` | — | 🚧 占位（未注册） |
| `/ban` | — | `@某人` | — | 🚧 占位（未注册） |

## 指令说明

### `/rand` — 生成随机数

**位置参数 `[min] [max] [count]`**

- 至少要给一个数字：只填一个数时视为 `max`（即 `0~max`），填两个数为 `min max`，三个数为 `min max count`
- `count` 默认 1，上限 100；要求 `min ≤ max`，否则回复参数错误

**开关 `-r <true|false>`**

- 设置返回的随机数**是否允许重复**：`-r true`（默认）逐个 `randint`；`-r false` 用 `random.sample`，此时 `count` 不能超过区间内的整数个数
- 该开关**只切换状态并回复提示，不会生成数字**，需要再发一次取值指令
- 状态是进程内全局变量：**对所有会话生效、不落盘**，插件重载后回到默认 `true`

```text
/rand 10           0~10 取 1 个
/rand 1 10 3       1~10 取 3 个（允许重复）
/rand -r false     关闭重复开关
/rand 1 10 3       1~10 取 3 个不重复
```

### `/time` — 时间与时区

- `/time`：按当前默认时区显示日期时间（含星期）与 Unix 时间戳，默认时区为北京时间（UTC+8）
- `/time <时区>`：按指定时区显示
- `/time setzone <时区>`：修改默认时区（只影响当前进程，插件重载后回到 UTC+8）

时区支持三种写法：`8` / `+8` / `-3.5` 这样的偏移、`UTC` / `CST` / `JST` 这样的缩写、`Asia/Shanghai` 这样的地区名。

### `/alarm` — 闹钟（AstrBot 定时任务）

闹钟被登记为 AstrBot 的**定时任务**，所以重载插件、重启 AstrBot 都不会丢，也能在 WebUI 的「未来任务」里查看和删除。

- `/alarm set <时间> <描述>`：设置闹钟
- `/alarm list`：查看本会话的闹钟（含工具直接登记的提醒任务）
- `/alarm del #<编号>`：取消闹钟，编号见 `/alarm list`；只能取消自己设置的，admin / owner 可以取消任意一条

**时间写法**（相对时间为起点是“现在”）：

| 写法 | 例子 |
| ------------------ | ---------------------------------------------- |
| 相对时间 | `+30s`、`+5m`、`+2h`、`+1d`（s 秒 / m 分 / h 时 / d 天） |
| Unix 时间戳 | `1790465400`（秒）、`1790465400123`（13 位按毫秒） |
| 日期时间 | `2026-09-27/07:30:00`、`2026-09-27/07:30`、`2026-09-27`、`09-27/07:30`、`09-27`、`07:30:00`、`07:30` |

只给时刻（如 `07:30`）时会补成今天，如果今天该时刻已过则顺延到明天。

**提醒方式**

- 默认：到点由插件直接发消息（basic 任务，**不消耗 token**）
- 描述末尾加 `-llm`：到点唤醒主 agent，让它用自己的语气组织提醒（active_agent 任务）

**配额**：单个会话最多 5 个闹钟，所有会话合计最多 50 个，描述不超过 100 字。

### `/rc` — 概率回复开关（admin）

开启后注册一条每 3 小时触发一次的定时任务，执行 `scripts/roll_ask.py` 掷骰（命中概率 1/8）：

- **未命中**：本轮直接结束，**连一次 LLM 调用都没有**
- **命中**：让当前会话的对话模型生成一个问题并发送；模型不可用时退回内置的兜底问题

`/rc on` 开启、`/rc off` 关闭、`/rc status` 查看状态与已命中次数。开关状态保存在 `randomchat_state.json`，关闭后脚本不再掷骰。

### `/op`、`/deop` — owner 与管理员

- `/op`（无参数）：认领 owner，**仅当还没有 owner 时**生效
- `/op @某人`：把对方加为管理员（owner 操作）
- `/op list`：查看管理员列表
- `/deop @某人`：撤回管理员（owner 操作）；owner 自己无法用指令撤回，请直接编辑 `usergroup.json`

目标用户 ID 从消息里的 @ 消息段提取（也支持直接打 QQ 号）。注意：**必须真正 @ 对方**，因为昵称里可能带空格，手打“@昵称”并不可靠。

### `/forcequit` — 退出 AstrBot（owner / admin）

回复后延迟 2 秒，先发 `SIGINT` 走 AstrBot 的正常退出流程；3 秒后仍未退出则强制结束进程。

### `/help`、`/ehelp` — 帮助

- `/help`：输出插件总览
- `/ehelp`（或 `/ext`）：输出插件总览
- `/ehelp <command>`：输出该指令的详细帮助，支持别名与 `/` 前缀（如 `/ehelp /random`），命令不存在时提示改用 `/ehelp ext`

帮助文本集中在 `core/help_text.py`，是帮助内容的唯一数据源：`EHELP_TEXT`（总览）、`HELP_TEXTS`（分命令）、`ALIASES`（别名归一）、`PENDING_COMMANDS`（占位指令），以及 `get_help_text()` / `not_found_text()` / `pending_text()` 三个查询接口。

## 权限体系（owner / admin / member）

等级表保存在 `usergroup.json`，是一张「用户 ID → 等级」的映射：

```json
{
    "123456789": "owner",
    "987654321": "admin"
}
```

- **等级数字**：`owner = 4`、`admin = 3`、`member = 1`、`baned = 0`；判定顺序 owner → admin → member
- **加载时机**：插件 `initialize()` 时读一次；每次 `/op`、`/deop` 修改成功后立即写盘并刷新内存中的 `Owner` / `Admin_list`
- **认领**：`/op`（无参数）谁先发谁成为 owner，请部署后第一时间认领；已有 owner 后该分支会拒绝
- **权限表**：`/op @某人`、`/deop` 需要 owner；`/edata`、`/rc`、`/forcequit` 需要 admin 及以上；其余指令所有人可用

## 数据与文件

插件数据放在 `<AstrBot>/data/plugin_data/astrbot_plugin_extra_commands/`：

| 文件 | 用途 | 状态 |
| ---------------------- | -------------------------------------- | -------- |
| `usergroup.json` | 用户等级表 `{ID: owner/admin/member}` | ✅ 使用中 |
| `randomchat_state.json` | `/rc` 开关、最近一次问题、命中次数 | ✅ 使用中 |
| `alarms.json` | 旧版闹钟记录；启动时迁移为定时任务后改名为 `alarms.json.bak` | ♻️ 已迁移 |

`scripts/roll_ask.py` 是 `/rc` 使用的掷骰脚本（stdout 打印 `HIT` / `MISS`，退出码 0 / 1），由 `/rc` 用子进程调用；它不是插件包的一部分，改脚本不需要重载插件。

## 安装

1. 把插件目录放到 AstrBot 的 `data/plugins/` 下，目录名为 `astrbot_plugin_extra_commands`
2. 重载插件，日志出现 `额外命令插件加载成功，占位指令：...` 即加载成功（数据目录会自动创建）
3. 部署后由管理员先发一次 `/op` 认领 owner

无第三方依赖，仅使用 Python 标准库与 AstrBot 内置 API（`/time` 的地区名时区需要 Python 自带的 `zoneinfo`，Windows 上需要 `tzdata`，AstrBot 环境默认已装）。

## 代码结构

```text
astrbot_plugin_extra_commands/
├── main.py            # 插件入口：Star 类、生命周期、每个命令的注册薄壳
├── commands/          # 一个命令一个模块（实现都在这里）
│   ├── help.py        # /help
│   ├── ehelp.py       # /ehelp
│   ├── edata.py       # /edata（占位）
│   ├── rand.py        # /rand
│   ├── time.py        # /time
│   ├── op.py          # /op
│   ├── deop.py        # /deop
│   ├── forcequit.py   # /forcequit
│   ├── alarm.py       # /alarm（含定时任务调度）
│   └── rc.py          # /rc（概率回复）
├── core/              # 与具体命令无关的公共设施
│   ├── storage.py     # 数据目录与 JSON 读写
│   ├── level.py       # 权限等级表与判定
│   ├── permissions.py # 命令权限校验（ensure_level）
│   ├── args.py        # 参数解析（含从 @ 段取用户 ID）
│   ├── timeutil.py    # 时间 / 时区 / 闹钟时间解析
│   ├── cron.py        # AstrBot 定时任务的公共操作
│   ├── handlers.py    # 命令处理器适配（异常 → 回复）
│   ├── exceptions.py  # 自定义异常
│   └── help_text.py   # 帮助文本库（纯数据，不依赖 astrbot）
├── scripts/
│   └── roll_ask.py    # /rc 的掷骰脚本（子进程调用，不由插件导入）
├── metadata.yaml      # 插件元信息
└── README.md
```

几条约定：

- **命令实现放 `commands/`，注册留 `main.py`**：AstrBot 依据 `handler.__module__` 把处理器绑定到插件实例上，如果 `@filter.command` 下沉到子模块，处理器拿不到插件实例、也不会被识别为该插件的命令。因此 `main.py` 里每个命令只保留一个薄壳：

  ```python
  @filter.command("rand", alias={"random"})
  @catch_command_error
  async def rand(self, event: AstrMessageEvent):
      """生成随机数"""
      yield await rand_command.run(self, event)
  ```

- **命令模块统一接口**：`async def run(plugin, event) -> MessageEventResult`，需要生命周期钩子的模块额外提供 `async def setup(plugin)`。
- **校验失败抛异常、由 `core.handlers` 统一回复**：`TooFewArgsError` / `TooManyArgsError` / `ArgsInputError` / `PermissionError` 都继承 `ExtraCommandsError`，`catch_command_error` 会把它转成一条回复（旧版是抛异常后用户什么都收不到）。
- **参数一律走 `core.args`**：`parse_args()` 校验数量，`parse_target_id()` 专门从消息末尾的 `@昵称(QQ号)` 里取用户 ID——AstrBot 会把 @ 段渲染成 ` @昵称(QQ号) `，昵称里的空格会让 `split()` 多切出几个“参数”。
- **文件读写一律走 `core.storage`**：`load_json()` / `save_json()`（先写临时文件再替换，失败会记日志）。

## 已知问题

- `/edata`、`/log`、`/ban` 尚未实现，其中 `/log`、`/ban` 还没有注册成指令
- 等级表里的 `baned` 目前不会被判定：`Level.id_of()` 只会返回 owner / admin / member，写 0 等同于 member
- `/rand -r` 的开关、`/time setzone` 的时区都只存在于当前进程，插件重载后回到默认值
- `/alarm`、`/rc` 依赖 AstrBot 的定时任务管理器（`context.cron_manager`），旧版本没有它时 `/alarm` 会提示无法设置
- `/alarm` 恢复 basic 任务处理器时会写入 `CronJobManager._basic_handlers`（AstrBot 未提供公开 API）
- `alarm list` 会把工具直接登记的任务（payload 里 `origin=tool`）一并列出，它们的名额不计入本插件的 5 个上限

## 许可证

GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。
