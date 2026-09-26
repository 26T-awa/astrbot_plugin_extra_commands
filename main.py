import asyncio
import os
import random
import re
import signal
import json
import time
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

try:  # 以包形式加载时优先使用相对导入
    from .help_text import (  # 命令帮助文本
        EHELP_TEXT,
        PENDING_COMMANDS,
        get_help_text,
        not_found_text,
        pending_text,
    )
    from .exceptions import (  # 自定义异常
        TooManyArgsError,
        TooFewArgsError,
        ArgsInputError,
        PermissionError,
    )
except ImportError:  # 兜底：插件被当作顶层模块加载时
    from help_text import (  # 命令帮助文本
        EHELP_TEXT,
        PENDING_COMMANDS,
        get_help_text,
        not_found_text,
        pending_text,
    )
    from exceptions import (  # 自定义异常
        TooManyArgsError,
        TooFewArgsError,
        ArgsInputError,
        PermissionError,
    )

PLUGIN_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugin_data"
    / "astrbot_plugin_extra_commands"
)
LEVEL_FILE = PLUGIN_DATA_DIR / "usergroup.json"
TIME_FILE = PLUGIN_DATA_DIR / "time.json"

OWNER = ""
ADMIN_LIST = []

RAND_DEFAULT_RANGE = (0, 99)  # /rand 的默认范围
RAND_MAX_COUNT = 100  # /rand 的最大生成数量
RAND_REPEAT = True

TZ_DEFAULT = timezone(timedelta(hours=8))  # 默认时区：北京时间（UTC+8）

ALARM_PER_SESSION = 5  # 单个会话内允许同时存在的待触发闹钟数量
ALARM_MAX_TOTAL = 50  # 所有会话合计的闹钟总数上限
ALARM_DESC_MAX_LEN = 100  # 闹钟描述的字符数上限
ALARM_ORIGIN = "extra_commands"  # 写在定时任务 payload 里的来源标记


@register("extra_commands", "_26T", "额外命令", "0.1")
class ExtraCommands(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._data_dir = PLUGIN_DATA_DIR
        self._data_path = self._data_dir / "data.json"
        self._time_path = self._data_dir / "time.json"
        self._level_path = self._data_dir / "usergroup.json"
        self._data_lock = asyncio.Lock()
        self._alarm_lock = asyncio.Lock()  # /alarm set 与 /alarm del 串行执行

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info(f"额外命令插件加载成功，占位指令：{', '.join(PENDING_COMMANDS)}")
        ExtraCommands._load_level()
        try:  # 先把数据目录准备好，闹钟记录会写在里面
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"创建插件数据目录失败：{e}")
        await self._setup_alarms()  # 闹钟是 AstrBot 的定时任务，启动时重新绑好处理器

    """
    静态方法列表
    """

    @staticmethod
    def _split_args(message_str: str) -> list[str]:
        """按空白切分消息并去掉指令本身，返回参数列表（不校验数量）。"""
        return message_str.strip().split()[1:]

    @staticmethod
    def _parse_args(message_str: str, range: tuple[int, int]) -> list[str]:
        """解析参数。需要传入参数数量范围，如(0,2)。若参数数量不符合范围则抛出异常。
        返回参数列表（不包含指令本身）。"""
        parts = message_str.strip().split()
        args_count = len(parts) - 1  # 去掉指令本身，参数数量

        if args_count < range[0]:  # 参数不足
            raise TooFewArgsError(args_count, range[0])
        elif args_count > range[1]:  # 参数过多
            raise TooManyArgsError(args_count, range[1])
        else:  # 参数数量符合范围
            parts = parts[1:]  # 去掉指令本身
            return parts

    @staticmethod
    def _load_level() -> bool:
        global OWNER
        global ADMIN_LIST
        if not LEVEL_FILE.exists():
            return False

        try:
            data = json.loads(LEVEL_FILE.read_text(encoding="utf-8"))
            OWNER = next((k for k, v in data.items() if v == "owner"), "")
            ADMIN_LIST = [k for k, v in data.items() if v == "admin"]
            return True
        except (json.JSONDecodeError, OSError):
            return False

    @staticmethod
    def _mdf_level(id: str, level: str, ownercommand: bool = False) -> bool:
        if LEVEL_FILE.exists():
            try:
                data = json.loads(LEVEL_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
        else:
            data = {}

        if ownercommand or (id != OWNER and level != "owner"):
            data[id] = level

        try:
            LEVEL_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
        except OSError:
            return False

        return ExtraCommands._load_level()

    @staticmethod
    def _get_level(id: str) -> str:
        if id is OWNER:
            return "owner"
        elif id in ADMIN_LIST:
            return "admin"
        else:
            return "member"

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        """读取 JSON 文件；文件不存在或解析失败时返回默认值。"""
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"读取 {path.name} 失败：{e}")
            return default

    @staticmethod
    def _write_json(path: Path, payload: Any) -> bool:
        """原子写入 JSON：先写临时文件再替换，避免中途失败写坏原文件。"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            os.replace(tmp, path)
            return True
        except OSError as e:
            logger.error(f"写入 {path.name} 失败：{e}")
            return False

    @staticmethod
    def _time_now() -> datetime:
        """当前时区时间。"""
        return datetime.now(TZ_DEFAULT)

    @staticmethod
    def _format_ts(ts: float) -> str:
        """把 Unix 秒格式化为北京时间字符串。"""
        return datetime.fromtimestamp(ts, TZ_DEFAULT).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """把秒数粗略格式化成「x天x小时x分钟」，不足一分钟时按秒显示。"""
        remain = int(max(0.0, seconds))
        days, remain = divmod(remain, 86400)
        hours, remain = divmod(remain, 3600)
        minutes, secs = divmod(remain, 60)

        chunks = []
        if days:
            chunks.append(f"{days}天")
        if hours:
            chunks.append(f"{hours}小时")
        if minutes:
            chunks.append(f"{minutes}分钟")
        if not chunks:
            chunks.append(f"{secs}秒")
        return "".join(chunks)

    """
    插件命令实现
    """

    # ========== help ==========
    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        """在官方文档后显示插件总览帮助"""
        yield event.plain_result(EHELP_TEXT)

    # ========== ehelp ==========
    @filter.command("ehelp", alias={"ext"})
    async def ehelp(self, event: AstrMessageEvent):
        """显示插件总览帮助，或查看指定命令的帮助信息"""
        logger.info(event.get_messages())

        target = self._parse_args(event.message_str, (0, 1))
        if not target:  # 无参数或 ext：输出总览
            yield event.plain_result(EHELP_TEXT)
            return
        else:  # 有参数：输出指定命令的帮助
            help_text = get_help_text(target[0])
            yield event.plain_result(
                help_text if help_text is not None else not_found_text(target[0])
            )

    # ========== edata ==========
    @filter.command("edata")
    async def edata(self, event: AstrMessageEvent):
        """管理插件数据"""
        yield event.plain_result(pending_text("data"))

    # ========== rand ==========
    @filter.command("rand", alias={"random"})
    async def rand(self, event: AstrMessageEvent):
        """生成随机数"""
        global RAND_REPEAT  # 允许重复的开关

        flag = re.search(r"-r\s+(\S+)", event.message_str, re.I)
        if not flag:
            args = self._parse_args(event.message_str, (1, 3))  # 最多 3 个数字
            if not args:
                raise TooFewArgsError(0, 1)
        elif flag.group(1).lower() == "true":
            yield event.plain_result(
                "⚠️ /rand -r true 已启用重复，若要关闭请使用 /rand -r false"
            )
            RAND_REPEAT = True
            return
        elif flag.group(1).lower() == "false":
            yield event.plain_result(
                "⚠️ /rand -r false 已关闭重复，若要开启请使用 /rand -r true"
            )
            RAND_REPEAT = False
            return
        else:
            raise ArgsInputError(flag.group(1), "true/false", get_help_text("rand"))

        # ---- 位置参数：min / max / count ----
        numbers = []
        for arg in args:
            try:
                numbers.append(int(arg))
            except ValueError:
                raise ArgsInputError(arg, "整数", get_help_text("rand"))

        low, high = RAND_DEFAULT_RANGE
        count = 1
        if len(numbers) == 1:  # 只给一个数时视为 max
            low, high = 0, numbers[0]
        elif len(numbers) >= 2:
            low, high = numbers[0], numbers[1]
        if len(numbers) == 3:
            count = numbers[2]

        minus = high - low + 1
        if minus <= 0:
            raise ArgsInputError(
                f"区间{low}>{high}", f"{low}<={high}", get_help_text("rand")
            )
        if not 1 <= count <= RAND_MAX_COUNT:
            raise ArgsInputError(
                f"数值{count}∉[1, {RAND_MAX_COUNT}]",
                f"{count}∈[1, {RAND_MAX_COUNT}]",
                get_help_text("rand"),
            )
        if not RAND_REPEAT and count > minus:
            raise ArgsInputError(
                f"数值{count}∉[1, {minus}]",
                f"{count}∈[1, {minus}]",
                get_help_text("rand"),
            )

        drawn = (
            [random.randint(low, high) for _ in range(count)]
            if RAND_REPEAT
            else random.sample(range(low, high + 1), count)
        )

        if count == 1:
            yield event.plain_result(f"🎲 随机数（{low}~{high}）：{drawn[0]}")
            return
        note = "" if RAND_REPEAT else "，不重复"
        yield event.plain_result(
            f"🎲 随机数（{low}~{high}，共 {count} 个{note}）："
            + "、".join(str(n) for n in drawn)
        )

    # ========== time ==========
    @filter.command("time")
    async def time(self, event: AstrMessageEvent):
        """显示时间"""
        global TZ_DEFAULT
        args = self._parse_args(event.message_str, (0, 2))
        if args:
            if args[0] == "setzone": # setzone ?
                if len(args) < 2:
                    raise TooFewArgsError(len(args), 2)
                else: # setzone <timezone>
                    _timezone = TZ_DEFAULT = timezone(timedelta(hours=int(args[1])))
                    yield event.plain_result(f"⚠️ 已设置默认时区为 {TZ_DEFAULT}")

            elif len(args) == 1 and args[0] in string.digits: # [timezone]
                _timezone = timezone(timedelta(hours=int(args[0])))

        else:
            _timezone = TZ_DEFAULT
        
        now = datetime.now(_timezone)
        weekday = "一二三四五六日"[now.weekday()]
        yield event.plain_result(
            f"🕒 当前时间：{now:%Y-%m-%d %H:%M:%S}（{_timezone} 星期{weekday}）\n"
            f"🔢 Unix 时间戳：{int(now.timestamp())}"
        )

    # ========== forcequit ==========
    async def _quit_process(delay: float = 2.0) -> None:
        """延迟退出：先让回复消息送达，再触发 AstrBot 的退出流程。"""
        await asyncio.sleep(delay)
        logger.warning("额外命令插件执行 /forcequit，正在退出 AstrBot 进程")
        try:
            signal.raise_signal(signal.SIGINT)  # 优先走 AstrBot 的正常退出流程
            await asyncio.sleep(3)
        except Exception as e:  # noqa: BLE001 - 非主线程等场景下退回强制退出
            logger.warning(f"发送退出信号失败，将强制退出：{e}")
        os._exit(0)

    @filter.command("forcequit", alias={"fq"})
    async def forcequit(self, event: AstrMessageEvent):
        """退出机器人（owner / admin）"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()

        if senderid != OWNER and senderid not in ADMIN_LIST:
            yield event.plain_result(str(PermissionError(self._get_level(senderid))))
            return

        logger.warning(
            f"收到 /forcequit：{event.get_sender_name()}（{senderid}）请求退出 AstrBot 进程"
        )
        yield event.plain_result("⚠️ 退出 AstrBot。")
        asyncio.create_task(self._quit_process())  # 让回复先送达，再退出

    # ========== op ==========
    @filter.command("op")
    async def op(self, event: AstrMessageEvent):
        """无参数：认领 owner；带用户 ID：添加管理员"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()
        targetid = re.search(r"\((\d{5,})\)\s*$", event.message_str)
        if targetid:
            targetid = targetid.group(1)
        else:
            targetid = ""
        senderlevel = self._get_level(senderid)

        if targetid:
            if senderid != OWNER and senderid not in ADMIN_LIST:  # 带参数：添加管理员
                yield event.plain_result(str(PermissionError(senderlevel, "owner")))
                return

            elif targetid == OWNER or targetid in ADMIN_LIST:
                yield event.plain_result(f"⚠️ {targetid} 已是 owner 或 管理员。")
                return

            else:
                self._mdf_level(targetid, "admin")
            yield event.plain_result(f"✅ 已添加管理员：{targetid}")

        else:
            if OWNER:
                yield event.plain_result(f"⚠️ 已有 owner（{OWNER}），无法认领。")
                return

            else:
                self._mdf_level(senderid, "owner", True)
                yield event.plain_result(f"👑 已认领 owner：{senderid}")
                return

    # ========== deop ==========
    @filter.command("deop")
    async def deop(self, event: AstrMessageEvent):
        """撤回管理员（owner 请直接编辑 json文件）"""
        global OWNER
        global ADMIN_LIST
        senderid = event.get_sender_id()
        targetid = re.search(r"\((\d{5,})\)\s*$", event.message_str)
        if targetid:
            targetid = targetid.group(1)
        else:
            targetid = ""
        senderlevel = self._get_level(senderid)

        if targetid:

            if senderid != OWNER:  # 带参数：撤回管理员
                yield event.plain_result(str(PermissionError(senderlevel, "owner")))
                return

            elif targetid not in ADMIN_LIST:
                yield event.plain_result(f"⚠️ {targetid} 不是管理员。")
                return

            else:
                self._mdf_level(targetid, "member")
            yield event.plain_result(f"🗑️ 已撤回管理员：{targetid}")

        else:
            raise TooFewArgsError(0, 1)

    # ========== alarm ==========
    def _get_cron_manager(self):
        """取 AstrBot 的定时任务管理器；拿不到时返回 None。"""
        return getattr(self.context, "cron_manager", None)

    @staticmethod
    def _parse_alarm_time(raw: str) -> float | None:
        """解析闹钟时间，失败时返回 None。

        支持三种写法：
        - 相对时间：+30s / +5m / +2h / +1d（s 秒、m 分、h 时、d 天）
        - Unix 时间戳：秒（10 位）或毫秒（13 位及以上）
        - 日期时间：2026-09-27/07:30、09-27/07:30、07:30 等
        """
        text = raw.strip()
        if not text:
            return None

        now = ExtraCommands._time_now()

        relative = re.fullmatch(r"\+(\d+(?:\.\d+)?)([smhd])", text, re.I)
        if relative:  # 相对时间：以当前时刻为起点
            unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}
            return (
                now.timestamp()
                + float(relative.group(1)) * unit[relative.group(2).lower()]
            )

        if re.fullmatch(r"\d{1,13}", text):  # 时间戳：13 位及以上按毫秒处理
            return int(text) / 1000 if len(text) >= 13 else float(int(text))

        for fmt in (
            "%Y-%m-%d/%H:%M:%S",
            "%Y-%m-%d/%H:%M",
            "%Y-%m-%d",
            "%m-%d/%H:%M:%S",
            "%m-%d/%H:%M",
            "%m-%d",
            "%H:%M:%S",
            "%H:%M",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
            except ValueError:
                continue
            if fmt.startswith("%H"):  # 只给时刻：补上今天
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            elif fmt.startswith("%m"):  # 只给月日：补上今年
                parsed = parsed.replace(year=now.year)
            parsed = parsed.replace(tzinfo=TZ_DEFAULT)
            if fmt.startswith("%H") and parsed <= now:  # 今天已过：顺延到明天
                parsed += timedelta(days=1)
            return parsed.timestamp()
        return None

    @staticmethod
    def _payload(job: Any) -> dict:
        """取定时任务的 payload；缺失或类型不对时返回空字典。"""
        payload = getattr(job, "payload", None)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _alarm_note(desc: str) -> str:
        """写给被唤醒的 agent 的纸条：让它用自己的语气把提醒发出去。"""
        return (
            "你之前定下的闹钟到点了。请用你一贯的语气提醒对方这件事："
            f"「{desc}」。简短自然，最好能结合具体情境，可以说明是因为约好的时间到了才来提醒；"
            "不要提到定时任务、cron 之类的技术细节，"
            "然后调用 send_message_to_user 把提醒发出去。"
        )

    @staticmethod
    def _job_run_ts(job: Any) -> float | None:
        """取一条定时任务的触发时间（Unix 秒）；取不到时返回 None。"""
        raw = ExtraCommands._payload(job).get("run_at")
        if isinstance(raw, str) and raw:
            try:
                return datetime.fromisoformat(raw).timestamp()
            except ValueError:
                pass
        next_run = getattr(job, "next_run_time", None)
        if isinstance(next_run, datetime):
            if next_run.tzinfo is None:  # 库里的时间统一按 UTC 存，但不带时区
                next_run = next_run.replace(tzinfo=timezone.utc)
            return next_run.timestamp()
        return None

    async def _setup_alarms(self) -> None:
        """启动时搬走旧闹钟，并给不需要 LLM 的闹钟重新绑上处理器。"""
        try:
            await self._migrate_legacy_alarms()
        except Exception as e:  # noqa: BLE001 - 迁移失败不能拖垮插件加载
            logger.error(f"迁移旧闹钟失败：{e}")
        try:
            await self._bind_basic_alarm_handlers()
        except Exception as e:  # noqa: BLE001 - 绑定失败只影响 basic 闹钟
            logger.error(f"绑定闹钟处理器失败：{e}")

    async def _bind_basic_alarm_handlers(self) -> None:
        """把 basic 闹钟重新绑回处理器：重启之后它们照样有人负责发消息。

        CronJobManager 只在新建 basic 任务时接收处理器，恢复已有任务只能直接
        写它的处理器表，所以这里会用到它的私有属性。
        """
        cron_mgr = self._get_cron_manager()
        if cron_mgr is None:
            return

        bound = 0
        for job in await cron_mgr.list_jobs("basic"):
            if self._payload(job).get("origin") != ALARM_ORIGIN:
                continue
            cron_mgr._basic_handlers[job.job_id] = self._fire_alarm
            bound += 1
        if bound:
            logger.info(f"额外命令插件重新绑定了 {bound} 个不经过 LLM 的闹钟")

    async def _migrate_legacy_alarms(self) -> None:
        """把旧版 alarms.json 里还没响的闹钟转成定时任务，再把文件改名存档。"""
        legacy_path = self._data_dir / "alarms.json"
        if not legacy_path.is_file():
            return

        cron_mgr = self._get_cron_manager()
        stored = self._read_json(legacy_path, {})
        items = stored.get("items") if isinstance(stored, dict) else None
        records = items if isinstance(items, list) else []

        now = time.time()
        moved = 0
        for record in records:
            if cron_mgr is None or not isinstance(record, dict):
                continue
            try:
                ts = float(record["ts"])
                umo = str(record["umo"])
            except (KeyError, TypeError, ValueError):
                continue
            if ts <= now or not umo:  # 已经过期，或者不知道要发往哪里
                continue

            desc = str(record.get("desc", ""))
            run_at = datetime.fromtimestamp(ts, TZ_DEFAULT)
            try:
                await self._create_alarm_job(
                    cron_mgr,
                    name=f"闹钟 #{record.get('id', '?')}",
                    desc=desc,
                    payload={
                        "origin": ALARM_ORIGIN,
                        "alarm_id": int(record.get("id") or 0),
                        "desc": desc,
                        "umo": umo,
                        "session": umo,
                        "creator": str(record.get("creator") or ""),
                        "creator_id": str(record.get("creator_id") or ""),
                        "created": float(record.get("created") or now),
                        "run_at": run_at.isoformat(),
                    },
                    run_at=run_at,
                    use_llm=False,
                )
                moved += 1
            except Exception as e:  # noqa: BLE001 - 单条失败不影响其它闹钟
                logger.error(f"迁移旧闹钟 #{record.get('id')} 失败：{e}")

        try:
            legacy_path.rename(legacy_path.with_name(legacy_path.name + ".bak"))
        except OSError as e:
            logger.error(f"重命名旧闹钟文件失败：{e}")
            return
        if moved:
            logger.info(f"额外命令插件把 {moved} 个旧闹钟迁移成了定时任务")

    async def _create_alarm_job(
        self,
        cron_mgr: Any,
        *,
        name: str,
        desc: str,
        payload: dict[str, Any],
        run_at: datetime,
        use_llm: bool,
    ) -> Any:
        """登记一条闹钟定时任务，返回创建好的任务对象。

        use_llm 为真：active_agent 任务，到点唤醒主 agent，让它自己组织语言发提醒；
        use_llm 为假：basic 任务，到点由插件直接发消息，不花 token。
        """
        if use_llm:
            return await cron_mgr.add_active_job(
                name=name,
                cron_expression=None,
                payload={**payload, "note": self._alarm_note(desc)},
                description=desc,
                run_once=True,
                run_at=run_at,
            )

        # add_basic_job 只能建循环任务，所以先建成「未启用」，再补上
        # run_once / run_at 并启用；中间出错就把半成品删掉，不留垃圾。
        job = await cron_mgr.add_basic_job(
            name=name,
            cron_expression=None,
            handler=self._fire_alarm,
            description=desc,
            payload=payload,
            enabled=False,
            persistent=True,
        )
        try:
            updated = await cron_mgr.update_job(
                job.job_id,
                run_once=True,
                cron_expression=None,
                payload=payload,
                enabled=True,
            )
        except Exception:
            await cron_mgr.delete_job(job.job_id)
            raise
        return updated or job

    async def _fire_alarm(self, **kwargs: Any) -> None:
        """basic 闹钟的处理器：到点直接发提醒，不经过 LLM。"""
        umo = str(kwargs.get("umo") or kwargs.get("session") or "")
        if not umo:
            logger.error("闹钟缺少投递目标，无法发送提醒")
            return

        alarm_id = kwargs.get("alarm_id", "?")
        text = f"⏰ 闹钟响啦（#{alarm_id}）：{kwargs.get('desc', '')}"
        created = kwargs.get("created")
        if kwargs.get("creator") and created:
            text += f"\n—— {kwargs['creator']} 于 {self._format_ts(created)} 设置"
        try:
            await self.context.send_message(umo, MessageChain([Comp.Plain(text)]))
        except Exception as e:  # noqa: BLE001 - 发送失败不应影响插件运行
            logger.error(f"闹钟 #{alarm_id} 提醒发送失败：{e}")

    async def _alarm_jobs(self, session: str | None = None) -> list[Any]:
        """列出本插件登记的闹钟任务，可按会话过滤，按触发时间排序。"""
        cron_mgr = self._get_cron_manager()
        if cron_mgr is None:
            return []
        try:
            jobs = await cron_mgr.list_jobs()
        except Exception as e:  # noqa: BLE001 - 读不到就当作没有闹钟
            logger.error(f"读取定时任务失败：{e}")
            return []

        picked = [
            job
            for job in jobs
            if self._payload(job).get("origin") == ALARM_ORIGIN
            and (session is None or self._payload(job).get("session") == session)
        ]
        return sorted(picked, key=lambda job: self._job_run_ts(job) or 0.0)

    async def _format_alarm_list(self, event: AstrMessageEvent) -> str:
        """列出当前会话的闹钟。"""
        jobs = await self._alarm_jobs(event.unified_msg_origin)
        if not jobs:
            return (
                "📭 本会话还没有闹钟，可用 /alarm set [时间] [描述] 设置一个。\n"
                + get_help_text("alarm")
            )

        now = time.time()
        lines = [f"⏰ 本会话待触发闹钟（{len(jobs)}/{ALARM_PER_SESSION}）："]
        for job in jobs:
            payload = self._payload(job)
            ts = self._job_run_ts(job)
            if ts is None:
                when, left = "时间未知", ""
            else:
                when = self._format_ts(ts)
                left = f"（{self._format_duration(ts - now)}后）"
            how = "LLM" if getattr(job, "job_type", "") == "active_agent" else "直发"
            lines.append(
                f"#{payload.get('alarm_id', '?')} {when}{left}· "
                f"{payload.get('desc', '')}（{how}）"
            )
        lines.append("以上闹钟都已登记在 AstrBot 后台的「未来任务」里。")
        return "\n".join(lines)

    async def _add_alarm(
        self, event: AstrMessageEvent, ts: float, desc: str, use_llm: bool
    ) -> str:
        """把闹钟登记成 AstrBot 的定时任务，返回回复文案。"""
        cron_mgr = self._get_cron_manager()
        if cron_mgr is None:
            return "❌ 当前 AstrBot 没有可用的定时任务管理器，无法设置闹钟。"

        umo = event.unified_msg_origin
        jobs = await self._alarm_jobs()
        same_session = [job for job in jobs if self._payload(job).get("session") == umo]
        if len(same_session) >= ALARM_PER_SESSION:
            return (
                f"❌ 本会话最多 {ALARM_PER_SESSION} 个闹钟，"
                "请先用 /alarm del [编号] 取消一个。"
            )
        if len(jobs) >= ALARM_MAX_TOTAL:
            return f"❌ 闹钟总数已达上限（{ALARM_MAX_TOTAL}）。"

        now = self._time_now()
        run_at = datetime.fromtimestamp(ts, TZ_DEFAULT)
        alarm_id = (
            max(
                (int(self._payload(job).get("alarm_id") or 0) for job in jobs),
                default=0,
            )
            + 1
        )

        try:
            job = await self._create_alarm_job(
                cron_mgr,
                name=f"闹钟 #{alarm_id}",
                desc=desc,
                payload={
                    "origin": ALARM_ORIGIN,
                    "alarm_id": alarm_id,
                    "desc": desc,
                    "umo": umo,
                    "session": umo,
                    "creator": event.get_sender_name() or event.get_sender_id(),
                    "creator_id": event.get_sender_id(),
                    "created": now.timestamp(),
                    "run_at": run_at.isoformat(),
                },
                run_at=run_at,
                use_llm=use_llm,
            )
        except Exception as e:  # noqa: BLE001 - 登记失败要给用户一个可见的提示
            logger.error(f"登记闹钟失败：{e}")
            return f"❌ 闹钟登记失败：{e}"

        how = (
            "到点唤醒 LLM，让它自己发提醒" if use_llm else "到点直接发提醒，不调用 LLM"
        )
        return (
            f"⏰ 闹钟已设置（#{alarm_id}，任务 ID {job.job_id}）\n"
            f"时间：{self._format_ts(ts)}"
            f"（{self._format_duration(ts - now.timestamp())}后）\n"
            f"描述：{desc}\n"
            f"方式：{how}\n"
            "已同步到 AstrBot 后台的「未来任务」，在那里也能查看或删除。"
        )

    async def _cancel_alarm(self, event: AstrMessageEvent, alarm_id: int) -> str:
        """取消指定闹钟，返回回复文案。"""
        cron_mgr = self._get_cron_manager()
        if cron_mgr is None:
            return "❌ 当前 AstrBot 没有可用的定时任务管理器。"

        session = event.unified_msg_origin
        for job in await self._alarm_jobs(session):
            payload = self._payload(job)
            if int(payload.get("alarm_id") or 0) != alarm_id:
                continue

            sender = event.get_sender_id()
            if (
                payload.get("creator_id") != sender
                and self._get_level(sender) == "member"
            ):
                return "❌ 只能取消自己设置的闹钟。"

            try:
                await cron_mgr.delete_job(job.job_id)
            except Exception as e:  # noqa: BLE001 - 删除失败要给用户一个可见的提示
                logger.error(f"取消闹钟 #{alarm_id} 失败：{e}")
                return f"❌ 取消闹钟 #{alarm_id} 失败：{e}"
            return f"🗑️ 已取消闹钟 #{alarm_id}（{payload.get('desc', '')}）。"

        return f"❌ 没有编号为 #{alarm_id} 的闹钟。"

    @filter.command("alarm")
    async def alarm(self, event: AstrMessageEvent):
        """设置闹钟"""
        # /alarm set +30s 打招呼 -llm
        # /alarm list
        flag = bool(event.message_str.endswith(" --llm" or " -llm"))
        args = self._parse_args(event.message_str, (0, 4))[0:3]  # 忽略"-llm"
        action = args[0].lower()
        match action:
            case "list":  # 查
                if len(args) > 1:
                    raise TooManyArgsError(len(args), 1)
                yield event.plain_result(self._format_alarm_list(event))
                return

            case "set":  # 设
                if len(args) <= 2:
                    raise TooFewArgsError(len(args), 3)
                else:  # args: [set, +30s, 打招呼]
                    # 得到时间
                    ts = self._parse_alarm_time(args[1])
                    if ts is None:
                        raise ArgsInputError(
                            args[1], "时间戳或日期时间", get_help_text("alarm")
                        )
                    if ts <= time.time():
                        yield event.plain_result(
                            f"❌ 「{args[1]}」对应的时间已经过去了，请换一个将来的时间。\n"
                            + get_help_text("alarm")
                        )
                        return
                    # time is OK
                    # 得到描述
                    desc = args[2]
                    if len(desc) > ALARM_DESC_MAX_LEN:
                        yield event.plain_result(
                            f"❌ 描述请控制在 {ALARM_DESC_MAX_LEN} 个字符以内。"
                        )
                        return
                    # describe is OK
                    # 登记闹钟
                    async with (
                        self._alarm_lock
                    ):  # /alarm set 与 /alarm del 串行执行，避免同时操作定时任务管理器
                        reply = await self._add_alarm(event, ts, desc, flag)
                    yield event.plain_result(reply)
                    return

            case "del":  # 删
                if len(args) <= 1:
                    raise TooFewArgsError(len(args), 2)
                else:  # args: [del, "#1"]
                    raw_id = args[1].lstrip("#")
                    if not raw_id.isdigit():
                        raise ArgsInputError(
                            args[1], "闹钟编号（数字）", get_help_text("alarm")
                        )
                    async with (
                        self._alarm_lock
                    ):  # /alarm set 与 /alarm del 串行执行，避免同时操作定时任务管理器
                        reply = await self._cancel_alarm(event, int(raw_id))
                    yield event.plain_result(reply)
                    return

            case _:  # 未知子命令
                raise ArgsInputError(action, "set / list / del", get_help_text("alarm"))

    """
    插件生命周期
    """

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # 闹钟现在是 AstrBot 的定时任务，不随插件停用而消失；
        # 这里保留 basic 任务的处理器绑定，停用期间到点也还能把提醒发出去。
        logger.info("额外命令插件已停用，闹钟作为 AstrBot 定时任务继续保留")
