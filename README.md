# astrbot-plugin-extra-commands

Extra commands for AstrBot.

> **现还处于测试阶段，功能不完善，欢迎大家提出建议**

## 指令架构：支持参数的注册范式

所有指令均为 `Star` 子类上的 `async def` + `yield` 生成器方法，用 `@filter.command(主指令, alias={别名...})` 注册，形成「装饰器声明 → 参数解析 → 业务执行 → 结果回复」四段式管线。

### 分层职责

| 层       | 载体                             | 职责                                          |
|---------|--------------------------------|---------------------------------------------|
| 注册层    | `@filter.command` + `alias`     | 声明触发词与中英别名，AstrBot 负责分发                     |
| 解析层    | 模块级 `_parse_*` 纯函数             | 从 `event.message_str` 抽取参数，返回 `(值, 错误消息)` 二元组 |
| 执行层    | 指令方法内的 `yield` 分支             | 参数校验 → 调用业务逻辑 → 收尾结算                        |
| 回复层    | `_image_reply` / `_render_reply` | 统一组装 `Image` + 可选 `Plain` 消息链                |

### 参数解析约定

参数统一从 `event.message_str` 以正则提取，采用「**无参数返回 `None`，非法参数返回错误文案**」的双返回约定，使长度、词典、难度三者可自由组合且互不干扰：

```python
def _parse_length(text: str, max_len: int) -> tuple[int | None, str | None]:
    m = re.search(r"-l\s+(\d+)", text, re.I)
    if not m:
        return None, None                 # 未传参：由调用方回退默认值
    length = int(m.group(1))
    if not (3 <= length <= max_len):
        return None, f"单词长度需在 3~{max_len} 之间。"
    return length, None                   # 合法：返回解析值
```

调用方据此短路返回错误、否则回退默认值：

```python
parsed_len, len_err = _parse_length(text, self._max_length)
if len_err:
    yield event.plain_result(len_err)
    return
length = parsed_len or self._default_length
```

### 要点提炼

- **生成器即状态机**：方法内任意 `return` / `yield` 即可结束本轮，错误分支无需嵌套，天然扁平
- **校验前置、纯函数化**：解析逻辑抽为无副作用的模块级函数，便于单测；指令方法只做编排
- **回复收敛到单点**：图片渲染统一走 `_render_reply`（`asyncio.to_thread` 卸载阻塞渲染），文本统一走 `event.plain_result`
- **子指令用正则分流**：如 `/wordle help`、`/dailyword reset` 在同一入口内按正则分支，不再额外占用触发词
- **别名覆盖中英文**：`alias={"猜词", "wd"}` 让同一逻辑同时服务中英用户

## 完整代码骨架

以下为可直接复用的最小范式：注册层声明指令，解析层抽取参数，执行层校验后编排，回复层统一封装消息链。

```python
"""参数化指令注册范式的最小骨架。"""

import asyncio
import re
from io import BytesIO

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

HELP_TEXT = (
    "🎯 指令帮助\n"
    "/demo [-l 长度] [-d 词典]：开局\n"
    "/demo help：查看帮助"
)


# ==================== 解析层：模块级纯函数 ====================

def _parse_length(text: str, max_len: int) -> tuple[int | None, str | None]:
    """解析 -l 长度参数：返回 (长度, 错误消息)；无 -l 时长度为 None。"""
    m = re.search(r"-l\s+(\d+)", text, re.I)
    if not m:
        return None, None
    length = int(m.group(1))
    if not (3 <= length <= max_len):
        return None, f"单词长度需在 3~{max_len} 之间。"
    return length, None


def _parse_dictionary(text: str) -> tuple[str | None, str | None]:
    """解析 -d 词典参数：返回 (词典名, 错误消息)；无 -d 时词典为 None。"""
    m = re.search(r"-d\s+([A-Za-z0-9]+)", text, re.I)
    if not m:
        return None, None
    name = m.group(1)
    if name not in get_dic_list():
        return None, f"词典「{name}」不可用，当前可用：{', '.join(get_dic_list())}"
    return name, None


def _mode_key(is_daily: bool, is_alt: bool) -> str:
    """按对局属性解析配色模式键：每日优先，其次备用模式，否则常规。"""
    return "daily" if is_daily else "alt" if is_alt else "normal"


# ==================== 回复层：统一封装消息链 ====================

def _create_image_component(img_data: bytes | BytesIO) -> Comp.Image:
    """包装字节数据为 AstrBot Image 组件。"""
    if isinstance(img_data, BytesIO):
        return Comp.Image.fromIO(img_data)
    return Comp.Image.fromBytes(img_data)


def _image_reply(event: AstrMessageEvent, img: bytes | BytesIO, text: str = ""):
    """图片回复：组装 Image 组件 + 可选 Plain 文本，返回待 yield 的结果对象。"""
    comps: list[Comp.Image | Comp.Plain] = [_create_image_component(img)]
    if text:
        comps.append(Comp.Plain(text))
    return event.chain_result(comps)


async def _render_reply(event, renderer, *args, text: str = ""):
    """后台线程渲染并组装图片回复，供命令 yield。"""
    img = await asyncio.to_thread(renderer, *args)
    return _image_reply(event, img, text)


# ==================== 注册层 + 执行层 ====================

class DemoPlugin(Star):
    """示例插件：演示支持参数的指令注册范式。"""

    def __init__(self, context: Context, config):
        super().__init__(context)
        self._max_length = config.get("max_length", 8)
        self._default_length = config.get("default_length", 5)
        self._default_dict = config.get("default_dict", "CET4")

    @filter.command("demo", alias={"演示", "dm"})
    async def cmd_demo(self, event: AstrMessageEvent):
        """开局指令：支持 -l 长度与 -d 词典，参数可自由组合。"""
        session_id = event.get_session_id()
        text = event.message_str.strip()

        # ① 子指令分流：同一入口内按正则判断，不额外占用触发词
        if re.search(r"\bhelp\b", text, re.I):
            yield event.plain_result(HELP_TEXT)
            return

        # ② 参数解析：任一非法即短路返回，否则回退默认值
        parsed_len, len_err = _parse_length(text, self._max_length)
        if len_err:
            yield event.plain_result(len_err)
            return
        length = parsed_len or self._default_length

        parsed_dict, dict_err = _parse_dictionary(text)
        if dict_err:
            yield event.plain_result(dict_err)
            return
        dictionary = parsed_dict or self._default_dict

        # ③ 业务执行：阻塞操作一律走 asyncio.to_thread
        try:
            word, meaning = await asyncio.to_thread(random_word, dictionary, length)
        except ValueError as e:
            yield event.plain_result(str(e))
            return
        await asyncio.to_thread(record_word, word, session_id)

        # ④ 状态登记 + 统一渲染回复
        game = Wordle(word, meaning, is_valid=legal_word)
        yield await self._open_game(
            event,
            session_id,
            game,
            style_key="normal",
            text="🎯 战局已开！\n/g <单词> 开猜",
        )

    @filter.command("demo_guess", alias={"dg"})
    async def cmd_guess(self, event: AstrMessageEvent):
        """提交指令：演示「有状态对话」中的参数校验与结算收尾。"""
        session_id = event.get_session_id()
        game_info = self._games.get(session_id)
        if game_info is None:
            yield event.plain_result("还没有进行中的战局～")
            return

        game = game_info.game
        parts = event.message_str.strip().split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请发送 /dg <单词>，例如 /dg apple")
            return

        word = parts[1].strip().lower()
        if len(word) != game.length:
            yield event.plain_result(f"单词长度应为 {game.length} 位，请再猜。")
            return

        guess_result = game.guess(word)
        if guess_result == GuessResult.DUPLICATE:
            yield event.plain_result("该词已被测试过了，换个方向吧～")
            return
        if guess_result == GuessResult.ILLEGAL:
            yield event.plain_result(f"「{word}」不是合法的英文单词，请换个词。")
            return

        img = await asyncio.to_thread(
            render_board_image, game, self._styles[_mode_key(False, False)]
        )
        yield await self._resolve_guess(event, session_id, game_info, guess_result, img)

    async def _open_game(self, event, session_id, game, *, text, style_key):
        """冲突检查 → 注册对局会话 → 渲染开局棋盘。"""
        if session_id in self._games:
            return event.plain_result("已有进行中的战局，请结束后再开局。")
        self._games[session_id] = GameSession(game=game)
        return await _render_reply(
            event, render_board_image, game, self._styles[style_key], text=text
        )

    async def _resolve_guess(self, event, session_id, game_info, guess_result, img):
        """按猜词结果收尾并返回结算回复。"""
        game = game_info.game
        if guess_result == GuessResult.WIN:
            self._stop_game(session_id)
            return _image_reply(event, img, f"🎉 不愧是你~\n{game.result}")
        if guess_result == GuessResult.LOSS:
            self._stop_game(session_id)
            return _image_reply(event, img, f"❌ 很遗憾，这就是结局。\n{game.result}")
        remaining = game.rows - len(game.guessed_words)
        return _image_reply(event, img, f"✅ 还剩 {remaining} 次机会")

    async def terminate(self):
        """插件热卸载前的静默清理。"""
        self._games.clear()
```

### 骨架拆解

| 步骤     | 代码位置                            | 要点                                    |
|--------|---------------------------------|---------------------------------------|
| ① 子指令  | `cmd_demo` 内首个正则分支              | `help` 等附属指令复用同一入口                    |
| ② 参数解析 | `_parse_length` / `_parse_dictionary` | 双返回约定，逐个 `if err: yield ...; return` |
| ③ 业务执行 | `asyncio.to_thread(...)`          | 阻塞调用不阻塞事件循环                           |
| ④ 状态与回复 | `_open_game` / `_resolve_guess`   | 状态登记与图片渲染各自收敛到单一方法                    |

### 扩展新指令清单

1. **加参数**：新增 `_parse_xxx(text) -> (值, 错误)`，在入口按序校验即可，无需改动既有分支
2. **加子指令**：在入口顶部追加一条正则分支，早于参数解析执行
3. **加别名**：扩展 `alias={...}` 集合，不影响逻辑
4. **加新模式**：扩展 `_mode_key` 的映射与 `self._styles` 的配色键，指令入口无需改动
