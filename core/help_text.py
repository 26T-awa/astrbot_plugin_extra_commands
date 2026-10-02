"""extra_commands 插件的帮助文本库（main.py 的外部依赖模块）。

本模块是帮助内容的**唯一数据源**：既保存 `/ehelp` 总览，也保存每个指令各自的
帮助文本。main.py 只负责注册指令并从这里取文本，避免帮助内容散落在实现中。

本模块不依赖 astrbot，可单独导入与测试。
"""

# ==================== 总览帮助（/ehelp、/help ext） ====================

EHELP_TEXT = """以下为插件Extra_Commands提供的额外命令。
/ehelp(/ext):弹出此帮助
    -/ehelp [command]  显示指定命令的帮助信息
= = = - - - = = = - - - = = =
实用命令：
/edata(/ed,/edt):管理用户自定义数据
/random(/rand):生成随机数
/time:显示时间
/alarm:设置闹钟
/rc(/randomchat):开关概率回复
/op:添加管理员
/deop:撤回管理员
/ban:拉黑用户，不再受理其任何消息
= = = - - - = = = - - - = = =
调试命令：
/forcequit:退出机器人
/log:查看最近的日志
"""

# ==================== 单指令帮助（键为主指令名） ====================

HELP_TEXTS: dict[str, str] = {
    "ehelp": """/ehelp(/ext) :弹出此帮助
    -/ehelp [command]  显示插件内指定命令的帮助信息""",

    "edata": """/edata(/ed,/edt) :管理每个用户的自定义数据（默认操作自己，@某人 需 admin）
    -/edata get [key] [@user]  查看数据；省略 key 时列出该用户全部数据
    -/edata set <key> <value> [@user]  新建或覆盖键值（value 会尝试按 JSON 解析）
    -/edata append <key> <value> [@user]  向列表类型的键追加一个元素
    -/edata mod <key> <value> [@user]  修改已存在的键
    -/edata del <key> [@user]  删除键
    -/edata keys [@user]  列出该用户的所有键
    -/edata clear [@user]  清空该用户的全部数据
    -@某人 只能放在整条指令的最末尾，且必须是真实艾特（渲染成 @昵称(QQ号)）；手打的数字或放在中间都会被当成普通参数""",

    "rand": """/rand(/random) :生成随机数
    -/rand [min] [max] [count]  生成随机数。默认范围为 0~99；min≤max；count为不超过100的生成数量，默认1个
    -/rand -r <true|false>  设置返回的随机数是否重复。默认重复""",

    "time": """/time :显示时间
    -/time [timezone]  显示指定时区的时间，默认显示本地时间。timezone为时区缩写或地区名，如“UTC”、“CST”、“Asia/Shanghai”
    -/time setzone <timezone>  设置默认时区""",

    "rc": """/rc(/randomchat) :开关概率回复（需 admin，按会话独立）
    -/rc on  对本会话开启：每 3 小时跑一次 roll_ask.py，命中才问一个问题
    -/rc off  对本会话关闭：脚本不再掷骰，完全安静
    -/rc status  查看本会话的开关状态
    -/rc list  查看所有开着概率回复的会话""",

    "alarm": """/alarm :设置闹钟
    -/alarm set <time> <desc>  设置闹钟，time为时间格式，具体有“+30s | +5m | +2h | +1d”、“2026-09-27/07:30 | 09-27/07:30 | 07:30”、“1790465400（时间戳）”，desc为描述
    -/alarm list  查看本会话已登记的闹钟
    -/alarm del #<id>  删除闹钟，id为闹钟编号""",

    # ---------------- 调试命令 ----------------
    "forcequit": """/forcequit :退出机器人""",

    "op": """/op :添加管理员。无参数时将认领Owner权限，请在plugin_data中修改usergroup.json文件的owner字段为自己的QQ号以完成认领
    -/op @<user>""",

    "deop": """/deop :撤回管理员
    -/deop @<user>""",

    "ban": """/ban :拉黑用户，不再受理其任何消息（含指令）（需 owner / admin）
    -/ban @<user>  拉黑，之后不再受理该用户的任何消息
    -/ban list  查看黑名单
    -/ban del @<user>  解除拉黑，恢复为普通成员""",

    "log": """/log :查看 AstrBot 最近的内存日志（需 owner / admin）
    -/log [n]  取最近 n 条日志（默认 50，上限 500）交给模型分析，并附带一份日志文件
    -/log [n] <问题>  把问题一并交给模型，让它针对日志回答
    -/log -f [n]  只导出日志文件，不调用模型""",
}

# ==================== 别名 ====================

# 主指令 -> 别名；查询帮助时别名会被归一为主指令
ALIASES: dict[str, tuple[str, ...]] = {
    "ehelp": ("ext",),
    "edata": ("ed", "edt"),
    "rand": ("random",),
    "time": (),
    "alarm": (),
    "rc": ("randomchat",),
    "op": (),
    "deop": (),
    "forcequit": ("fq",),
    "log": (),
}

# ==================== 文案模板 ====================

NOT_FOUND_TEXT = "未找到命令 {command} 的帮助信息，请使用 /ehelp ext 查看所有可用命令。"


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
