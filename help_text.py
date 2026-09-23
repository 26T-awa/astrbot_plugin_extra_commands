"""extra_commands 插件的帮助文本库（main.py 的外部依赖模块）。

本模块是帮助内容的**唯一数据源**：既保存 `/ehelp` 总览，也保存每个指令各自的
帮助文本。main.py 只负责注册指令并从这里取文本，避免帮助内容散落在实现中。

本模块不依赖 astrbot，可单独导入与测试。
"""

# ==================== 总览帮助（/ehelp、/help ext） ====================

EHELP_TEXT = """以下为插件Extra_Commands提供的额外命令，部分命令尚未实现，使用时请注意。
/ehelp(/ext):弹出此帮助
    -/ehelp [command]  显示指定命令的帮助信息
= = = - - - = = = - - - = = =
实用命令：
/data · · · :管理数据

/random(/rand)
            :生成随机数

/time · · · :显示时间
/alarm  · · :设置闹钟

= = = - - - = = = - - - = = =
调试命令：
/forcequit  :退出机器人

/log  · · · :查看日志
"""

# ==================== 单指令帮助（键为主指令名） ====================

HELP_TEXTS: dict[str, str] = {
    "ehelp": """/ehelp(/ext) :弹出此帮助
    -/ehelp [command]  显示插件内指定命令的帮助信息""",

    # ---------------- 实用命令 ----------------
    "data": """/data :管理数据
    -/data get [key]  获取数据
    -/data set [key] [value]  设置数据
    -/data del [key]  删除数据
    -/data mod [key] [value]  修改数据""",

    "rand": """/rand(/random) :生成随机数
    -/rand [min] [max] [count]  生成随机数。默认范围为 0~99；min≤max；count为不超过100的生成数量，默认1个
    -/rand -r <true|false>  设置返回的随机数是否重复。默认重复""",

    "time": """/time :显示时间""",

    "alarm": """/alarm :设置闹钟
    -/alarm set [timestamp] [desc]  设置闹钟，timestamp为时间戳，desc为描述""",

    # ---------------- 调试命令 ----------------
    "forcequit": """/forcequit :退出机器人""",

    "log": """/log :查看日志
    -/log [n]  查看最近n条日志，默认10条""",
}

# ==================== 别名与占位指令 ====================

# 主指令 -> 别名；查询帮助时别名会被归一为主指令
ALIASES: dict[str, tuple[str, ...]] = {
    "ehelp": ("ext",),
    "rand": ("random",),
}

# 尚未实现、需以最简形式注册的指令：
# 注册后它们才会出现在指令表中，`/ehelp <command>` 也能查到对应帮助。
PENDING_COMMANDS: tuple[str, ...] = (
    "data",
    "rand",
    "time",
    "alarm",
    "forcequit",
    "log",
)

# ==================== 文案模板 ====================

NOT_FOUND_TEXT = "未找到命令 {command} 的帮助信息，请使用 /ehelp ext 查看所有可用命令。"
PENDING_TEXT = "⚠️ /{command} 尚未实现，以下为该指令的规划用法：\n{help}"


# ==================== 查询接口 ====================


def normalize(command: str) -> str:
    """把用户输入归一为主指令名：去掉 `/`、`-` 前缀并转小写，别名归一到主名。"""
    name = command.strip().lstrip("/-").lower()
    for main, aliases in ALIASES.items():
        if name in aliases:
            return main
    return name


def get_help_text(command: str) -> str | None:
    """按指令名取帮助文本，支持 `/data`、别名等写法；未知指令返回 None。"""
    return HELP_TEXTS.get(normalize(command))


def not_found_text(command: str) -> str:
    """未知指令的提示文案。"""
    return NOT_FOUND_TEXT.format(command=command)


def pending_text(command: str) -> str:
    """占位指令的回复：说明尚未实现，并附上该指令的规划用法。"""
    main = normalize(command)
    return PENDING_TEXT.format(command=main, help=HELP_TEXTS.get(main, ""))
