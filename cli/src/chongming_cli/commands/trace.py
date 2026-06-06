"""
chongming trace 命令 - 实时或历史追踪 NATS 请求-响应链路

自动关联 request_id 并打印清晰的输出，持续追踪 worker 请求与响应。

使用方式::

    # 追踪一次请求-响应
    chongming trace user.register

    # 持续追踪
    chongming trace user.register --follow

    # 追踪 3 次后退出
    chongming trace user.register --count 3

    # 回放最近 1 小时的请求-响应（需要 JetStream）
    chongming trace user.register --since 1h --js

    # 美化输出，隐藏请求 payload
    chongming trace user.register --pretty --no-request-payload
"""

import argparse
import asyncio
import json
import logging
import re
import signal
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

# 抑制 nats 库自身的冗余日志
logging.getLogger("nats").setLevel(logging.WARNING)
logging.getLogger("nats.aio.client").setLevel(logging.WARNING)

# ── ANSI 颜色代码 ─────────────────────────────────────────────────────
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_BLUE = "\033[34m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_WHITE = "\033[37m"
_RESET = "\033[0m"

# ── 全局常量 ──────────────────────────────────────────────────────────
RESPONSE_TIMEOUT = 5  # 等待响应超时时间（秒）

# 默认需要脱敏的字段名（全小写匹配）
SENSITIVE_FIELDS = {
    "password", "secret", "token", "credential", "credit_card",
    "ssn", "secret_key", "api_key", "access_key", "private_key",
}


# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════

def _parse_duration(duration: str) -> timedelta:
    """解析持续时间字符串（如 1h、30m、10s、7d）

    :raises ValueError: 格式无效时抛出
    """
    match = re.match(r"^(\d+)([smhd])$", duration)
    if not match:
        raise ValueError(
            f"无效的持续时间格式: '{duration}'，请使用如 1h、30m、10s、7d"
        )
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


def _format_timestamp(dt: Optional[datetime] = None) -> str:
    """格式化为带颜色的时间戳"""
    if dt is None:
        dt = datetime.now()
    ts = dt.strftime("[%Y-%m-%d %H:%M:%S]")
    return f"{_DIM}{ts}{_RESET}"


def _color_subject(subject: str) -> str:
    """给 subject 加上粗体颜色"""
    return f"{_BOLD}{_WHITE}{subject}{_RESET}"


def _color_request_id(request_id: str) -> str:
    """给 request_id 加上颜色"""
    return f"{_YELLOW}{request_id}{_RESET}"


def _color_duration(seconds: float) -> str:
    """给耗时加上颜色"""
    return f"{_MAGENTA}{seconds:.2f}s{_RESET}"


def _mask_sensitive_fields(data: Any, fields: set = SENSITIVE_FIELDS) -> Any:
    """递归脱敏 dict 中匹配敏感字段名的值，替换为 ``***``"""
    if isinstance(data, dict):
        return {
            k: ("***" if (isinstance(k, str) and k.lower() in fields)
                else _mask_sensitive_fields(v, fields))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive_fields(item, fields) for item in data]
    return data


def _format_payload(data: Any, pretty: bool) -> str:
    """将 payload 格式化为 JSON 字符串"""
    if pretty:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return json.dumps(data, ensure_ascii=False, default=str)


def _safe_parse_json(raw: bytes) -> Any:
    """安全解析 JSON，失败时返回包含原始数据的占位 dict"""
    try:
        return json.loads(raw.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"_raw": raw.decode(errors="replace")}


# ══════════════════════════════════════════════════════════════════════
# 参数解析
# ══════════════════════════════════════════════════════════════════════

def add_trace_parser(subparsers):
    """注册 trace 子命令的参数解析器"""
    parser = subparsers.add_parser(
        "trace",
        help="实时或历史追踪 NATS 请求-响应链路",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 追踪一次请求-响应
  chongming trace user.register

  # 持续追踪
  chongming trace user.register --follow

  # 追踪 3 对后退出
  chongming trace user.register --count 3

  # 回放最近 1 小时（需要 JetStream）
  chongming trace user.register --since 1h --js

  # 美化输出，隐藏 payload
  chongming trace user.register --pretty --no-request-payload --no-response-payload

  # 指定 NATS 地址和凭证
  chongming trace user.register --host nats.example.com --port 4222 --creds ./nats.creds

  # 使用 TLS 加密
  chongming trace user.register --tls --tls-ca ./ca.pem
        """,
    )
    parser.add_argument(
        "subjects",
        type=str,
        nargs="+",
        help="要追踪的业务主题，如 user.register，支持同时监听多个",
    )
    parser.add_argument(
        "--follow", "-f",
        action="store_true",
        help="持续监听，直到手动停止（Ctrl+C）",
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=None,
        help="接收 N 对请求-响应后自动退出（默认 1，--follow 模式下默认无限）",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="使用 JetStream 回放最近一段时间的历史消息（如 1h、30m），自动启用 --js",
    )
    parser.add_argument(
        "--js",
        action="store_true",
        help="启用 JetStream 模式（用于历史回放或访问持久化主题）",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="美化输出 JSON（多行缩进）",
    )
    parser.add_argument(
        "--no-request-payload",
        action="store_true",
        help="不打印请求 payload",
    )
    parser.add_argument(
        "--no-response-payload",
        action="store_true",
        help="不打印响应 payload",
    )

    # ── NATS 连接参数 ────────────────────────────────────────────────
    conn = parser.add_argument_group("NATS 连接参数")
    conn.add_argument("--host", type=str, default="localhost",
                      help="NATS 服务器地址（默认 localhost）")
    conn.add_argument("--port", "-p", type=int, default=4222,
                      help="NATS 服务器端口（默认 4222）")
    conn.add_argument("--user", type=str, default=None, help="NATS 用户名")
    conn.add_argument("--password", type=str, default=None, help="NATS 密码")
    conn.add_argument("--token", type=str, default=None, help="NATS 令牌")
    conn.add_argument("--creds", type=str, default=None,
                      help="NATS 用户凭证文件路径（.creds）")
    conn.add_argument("--nkey", type=str, default=None,
                      help="NKEY 种子文件路径（.nk）")
    conn.add_argument("--tls", action="store_true", help="启用 TLS 加密连接")
    conn.add_argument("--tls-cert", type=str, default=None,
                      help="TLS 客户端证书路径")
    conn.add_argument("--tls-key", type=str, default=None,
                      help="TLS 客户端密钥路径")
    conn.add_argument("--tls-ca", type=str, default=None,
                      help="TLS CA 证书路径")

    # ── JetStream 参数 ───────────────────────────────────────────────
    js_group = parser.add_argument_group("JetStream 参数（--since/--js 模式）")
    js_group.add_argument("--stream", type=str, default=None,
                          help="JetStream Stream 名称（默认自动推断）")
    js_group.add_argument("--js-domain", type=str, default=None,
                          help="JetStream 域名")
    js_group.add_argument("--list-streams", action="store_true",
                          help="列出所有可用的 JetStream Stream 并退出")


# ══════════════════════════════════════════════════════════════════════
# 命令入口
# ══════════════════════════════════════════════════════════════════════

def handle_trace(args):
    """处理 trace 命令的同步入口"""
    asyncio.run(_run_trace(args))


async def _run_trace(args):
    """异步主逻辑"""

    # ── 计算停止条件 ─────────────────────────────────────────────────
    max_count = args.count
    if max_count is None:
        max_count = -1 if args.follow else 1   # -1 = 无限

    if args.since and not args.js:
        args.js = True  # --since 自动启用 JetStream

    # 使用可变容器追踪已捕获对数（避免跨作用域 nonlocal 问题）
    counter: Dict[str, int] = {"value": 0}

    shutdown_event = asyncio.Event()

    # 注册信号处理器（SIGINT / SIGTERM 触发优雅退出）
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    nc: Optional[NATS] = None

    try:
        nc = await _connect_nats(args)

        subjects = args.subjects

        if args.list_streams:
            await _list_streams(nc)
            return

        if args.js and args.since:
            since_delta = _parse_duration(args.since)
            await _js_trace(nc, args, subjects, since_delta, max_count, shutdown_event, counter)
        else:
            await _core_trace(nc, args, subjects, max_count, shutdown_event, counter)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        if nc and nc.is_connected:
            try:
                await nc.drain()
            except Exception:
                pass
            try:
                await nc.close()
            except Exception:
                pass
            print(file=sys.stderr)
            print(f"{_CYAN}NATS 连接已关闭{_RESET}", file=sys.stderr)
        print(f"{_DIM}追踪结束，共捕获 {_BOLD}{counter['value']}{_RESET}{_DIM} 对请求-响应{_RESET}",
              file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════
# NATS 连接
# ══════════════════════════════════════════════════════════════════════

async def _connect_nats(args) -> NATS:
    """根据命令行参数连接 NATS 并返回客户端"""
    urls = f"nats://{args.host}:{args.port}"

    opts: Dict[str, Any] = {
        "servers": [urls],
        "name": "chongming-trace",
        "connect_timeout": 10,
    }

    # 认证
    if args.user and args.password:
        opts["user"] = args.user
        opts["password"] = args.password
    if args.token:
        opts["token"] = args.token
    if args.creds:
        opts["user_credentials"] = args.creds
    if args.nkey:
        opts["nkeys_seed"] = args.nkey

    # TLS
    if args.tls or args.tls_cert or args.tls_key or args.tls_ca:
        ssl_ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if args.tls_ca:
            ssl_ctx.load_verify_locations(cafile=args.tls_ca)
        if args.tls_cert and args.tls_key:
            ssl_ctx.load_cert_chain(certfile=args.tls_cert, keyfile=args.tls_key)
        opts["tls"] = ssl_ctx

    print(f"{_DIM}正在连接 NATS: {urls}{_RESET}", file=sys.stderr)
    nc = await nats.connect(**opts)
    print(f"{_GREEN}已连接到 NATS{_RESET}", file=sys.stderr)
    print(file=sys.stderr)
    return nc


# ══════════════════════════════════════════════════════════════════════
# Core NATS 追踪（实时监听）
# ══════════════════════════════════════════════════════════════════════

async def _core_trace(
    nc: NATS,
    args: argparse.Namespace,
    subjects: list,
    max_count: int,
    shutdown_event: asyncio.Event,
    counter: Dict[str, int],
):
    """Core NATS 实时追踪

    监听业务 subject，当收到请求时临时订阅 reply 主题，
    收到响应或超时后取消订阅。

    :param counter: 可变计数器，跟踪已捕获的请求-响应对数
    """

    pending: Dict[str, Dict] = {}
    # pending[reply_subject] = {"request_id": str, "timer_task": asyncio.Task}

    subject_set = set(subjects)

    async def on_request(msg: Msg) -> None:
        """收到业务 subject 请求"""
        headers = msg.headers or {}
        request_id = headers.get("request_id", "")
        reply_subject = msg.reply

        if not reply_subject or msg.subject not in subject_set:
            return

        req_data = _mask_sensitive_fields(_safe_parse_json(msg.data))

        # 打印请求
        now = datetime.now()
        if request_id:
            rid_label = f"[request_id={_color_request_id(request_id)}]"
        else:
            rid_label = f"[{_DIM}no request_id{_RESET}]"
        print(f"{_format_timestamp(now)} {rid_label} "
              f"{_BOLD}{_GREEN}REQ{_RESET} {_color_subject(msg.subject)} "
              f"{_DIM}(duration: waiting...){_RESET}")

        if not args.no_request_payload:
            print(f"  {_DIM}Payload:{_RESET} {_format_payload(req_data, args.pretty)}")
        print()

        start_time = time.monotonic()

        # ── 响应回调 ──────────────────────────────────────────────
        async def on_reply(resp: Msg) -> None:
            info = pending.pop(resp.subject, None)
            if info is None:
                return

            timer = info.get("timer_task")
            if timer and not timer.done():
                timer.cancel()

            rid = info["request_id"]
            elapsed = time.monotonic() - start_time

            resp_data = _mask_sensitive_fields(_safe_parse_json(resp.data))

            if rid:
                rid_label2 = f"[request_id={_color_request_id(rid)}]"
            else:
                rid_label2 = f"[{_DIM}no request_id{_RESET}]"
            print(f"{_format_timestamp()} {rid_label2} "
                  f"{_BOLD}{_BLUE}RSP{_RESET} "
                  f"({_DIM}took{_RESET} {_color_duration(elapsed)})")

            if not args.no_response_payload:
                print(f"  {_DIM}Payload:{_RESET} {_format_payload(resp_data, args.pretty)}")
            print()

            counter["value"] += 1
            if 0 < max_count <= counter["value"]:
                shutdown_event.set()

        # 动态订阅 reply 主题
        sub = await nc.subscribe(reply_subject, cb=on_reply)

        # ── 超时任务 ──────────────────────────────────────────────
        async def timeout() -> None:
            await asyncio.sleep(RESPONSE_TIMEOUT)
            if reply_subject not in pending:
                return
            pending.pop(reply_subject, None)
            try:
                await sub.unsubscribe()
            except Exception:
                pass

            rid = request_id
            if rid:
                rid_label3 = f"[request_id={_color_request_id(rid)}]"
            else:
                rid_label3 = f"[{_DIM}no request_id{_RESET}]"
            print(f"{_format_timestamp()} {rid_label3} "
                  f"{_BOLD}{_RED}RSP{_RESET} "
                  f"({_RED}timeout after {RESPONSE_TIMEOUT}s{_RESET})")
            print()

            counter["value"] += 1
            if 0 < max_count <= counter["value"]:
                shutdown_event.set()

        timer = asyncio.create_task(timeout())
        pending[reply_subject] = {
            "request_id": request_id,
            "timer_task": timer,
        }

    # 订阅所有业务主题
    for subject in subjects:
        await nc.subscribe(subject, cb=on_request)
    subject_list = ", ".join(_bold_subject(s) for s in subjects)
    print(f"{_CYAN}正在监听{_RESET} {subject_list} ...", file=sys.stderr)
    print(f"{_DIM}按 Ctrl+C 停止追踪{_RESET}", file=sys.stderr)
    print(file=sys.stderr)

    await shutdown_event.wait()


def _bold_subject(subject: str) -> str:
    """stderr 版本：加粗白色"""
    return f"{_BOLD}{_WHITE}{subject}{_RESET}"


# ══════════════════════════════════════════════════════════════════════
# JetStream 追踪（历史回放）
# ══════════════════════════════════════════════════════════════════════

async def _js_trace(
    nc: NATS,
    args: argparse.Namespace,
    subjects: list,
    since_delta: timedelta,
    max_count: int,
    shutdown_event: asyncio.Event,
    counter: Dict[str, int],
):
    """JetStream 模式：回放 since 时间以来的消息，然后可切换到实时"""

    js = nc.jetstream()

    # 推断 stream 名称: `{首段大写}_STREAM`
    first_subject = subjects[0]
    stream = args.stream or f"{first_subject.split('.')[0].upper()}_STREAM"

    start_time = datetime.now(tz=timezone.utc) - since_delta
    subject_list = ", ".join(subjects)
    print(f"{_CYAN}历史回放:{_RESET} 最近 {_BOLD}{args.since}{_RESET} 的消息",
          file=sys.stderr)
    print(f"{_DIM}Subjects:  {subject_list}{_RESET}", file=sys.stderr)
    print(f"{_DIM}起始时间: {start_time.isoformat()}{_RESET}", file=sys.stderr)
    print(f"{_DIM}Stream:    {stream}{_RESET}", file=sys.stderr)
    print(file=sys.stderr)

    import nats.js.api as js_api

    consumer_cfg = js_api.ConsumerConfig(
        deliver_policy=js_api.DeliverPolicy.BY_START_TIME,
        opt_start_time=start_time,
        ack_policy=js_api.AckPolicy.EXPLICIT,
        max_deliver=1,
        inactive_threshold=float(RESPONSE_TIMEOUT * 2),  # seconds
    )

    try:
        psub = await js.pull_subscribe(
            first_subject,
            stream=stream,
            durable=None,        # ephemeral，用完即弃
            config=consumer_cfg,
        )
    except nats.errors.BadSubjectError:
        print(f"{_RED}错误:{_RESET} Stream '{stream}' 或 subject '{first_subject}' 不存在",
              file=sys.stderr)
        _print_stream_hint()
        sys.exit(1)
    except nats.js.errors.NotFoundError:
        print(f"{_RED}错误:{_RESET} Stream '{stream}' 不存在（自动推断自 subject '{first_subject}'）",
              file=sys.stderr)
        _print_stream_hint()
        sys.exit(1)
    except Exception as e:
        print(f"{_RED}JetStream 订阅失败:{_RESET} {e}", file=sys.stderr)
        sys.exit(1)

    replaying = True

    while replaying and not shutdown_event.is_set():
        try:
            msgs = await psub.fetch(batch=50, timeout=1.0)
        except asyncio.TimeoutError:
            replaying = False
            break
        except Exception:
            replaying = False
            break

        for msg in msgs:
            await msg.ack()
            _handle_js_message(msg, args, counter, shutdown_event)

            if shutdown_event.is_set() or (0 < max_count <= counter["value"]):
                break

    if shutdown_event.is_set() or (0 < max_count <= counter["value"]):
        return

    print(f"{_GREEN}历史消息回放完成{_RESET}", file=sys.stderr)

    # 如果 --follow → 切换到实时监听
    if args.follow:
        print(f"{_CYAN}进入实时监听模式...{_RESET}", file=sys.stderr)
        print(file=sys.stderr)
        await _core_trace(nc, args, subjects, max_count, shutdown_event, counter)


def _print_stream_hint() -> None:
    """打印提示信息，引导用户使用 --list-streams"""
    print(file=sys.stderr)
    print(f"  {_DIM}提示:{_RESET} 使用 {_BOLD}chongming trace <subject> --list-streams{_RESET} 查看所有可用 Stream",
          file=sys.stderr)
    print(file=sys.stderr)


async def _list_streams(nc: NATS) -> None:
    """列出所有可用的 JetStream Stream 并退出"""
    try:
        js = nc.jetstream()
        names = await js.streams_info()
    except Exception as e:
        print(f"{_RED}获取 Stream 列表失败:{_RESET} {e}", file=sys.stderr)
        sys.exit(1)

    if not names:
        print(f"{_YELLOW}没有找到任何 JetStream Stream{_RESET}", file=sys.stderr)
        return

    print(f"{_CYAN}可用的 JetStream Stream:{_RESET}", file=sys.stderr)
    print(file=sys.stderr)
    for stream_info in names:
        config = stream_info.config
        state = stream_info.state
        subjects = ", ".join(config.subjects) if config.subjects else "(none)"
        print(f"  {_BOLD}{_WHITE}{config.name}{_RESET}")
        print(f"    {_DIM}Subjects:{_RESET} {subjects}")
        print(f"    {_DIM}Messages:{_RESET} {state.messages}  "
              f"{_DIM}Consumers:{_RESET} {state.consumer_count}")
        print()


def _handle_js_message(
    msg: Msg,
    args: argparse.Namespace,
    counter: Dict[str, int],
    shutdown_event: asyncio.Event,
) -> None:
    """处理和打印一条 JetStream 拉取到的历史消息

    对于历史消息，只打印请求信息并标注 '(history)'，不等待响应。
    """
    headers = msg.headers or {}
    request_id = headers.get("request_id", "")
    reply_subject = msg.reply

    if not reply_subject:
        return

    # 尝试从 JetStream metadata 获取消息时间
    msg_time: Optional[datetime] = None
    try:
        if hasattr(msg, "metadata") and msg.metadata:
            msg_time = msg.metadata.timestamp
    except (AttributeError, TypeError, ValueError):
        pass

    req_data = _mask_sensitive_fields(_safe_parse_json(msg.data))

    if request_id:
        rid_label = f"[request_id={_color_request_id(request_id)}]"
    else:
        rid_label = f"[{_DIM}no request_id{_RESET}]"
    print(f"{_format_timestamp(msg_time)} {rid_label} "
          f"{_BOLD}{_GREEN}REQ{_RESET} {_color_subject(msg.subject)} "
          f"{_YELLOW}(history){_RESET} {_DIM}(duration: waiting...){_RESET}")

    if not args.no_request_payload:
        print(f"  {_DIM}Payload:{_RESET} {_format_payload(req_data, args.pretty)}")
    print()

    # 历史消息：不等待响应
    print(f"{_format_timestamp()} {rid_label} "
          f"{_BOLD}{_RED}RSP{_RESET} {_YELLOW}(history - no response available){_RESET}")
    print()

    counter["value"] += 1
    if 0 < args.count and counter["value"] >= args.count:
        shutdown_event.set()