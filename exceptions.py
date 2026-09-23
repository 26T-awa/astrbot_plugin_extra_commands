"""
自定义异常处理
"""

# error.py

class ExtraCommandsError(Exception):
    """机器人所有自定义异常的基类"""
    pass
    

class TooManyArgsError(ExtraCommandsError):
    """参数过多"""
    def __init__(self, got: int, limit: int):
        self.got = got
        self.limit = limit
        super().__init__(f"参数过多！（{got} > {limit}）")


class TooFewArgsError(ExtraCommandsError):
    """参数不足"""
    def __init__(self, got: int, limit: int):
        self.got = got
        self.limit = limit
        super().__init__(f"参数不足！（{got} < {limit}）")


class ArgsInputError(ExtraCommandsError):
    """参数错误"""
    def __init__(self, got: str, limit: str, help_text: str = None):
        self.got = got
        self.limit = limit
        self.help_text = help_text
        if help_text is not None:
            super().__init__(f"参数错误！（理应得到 {limit}，实际上是 {got}）\n{help_text}")
        else:
            super().__init__(f"参数错误！（理应得到 {limit}，实际上是 {got}）")