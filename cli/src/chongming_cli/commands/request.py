"""
chongming request 命令 - 直接发送 NATS 请求到 Worker（绕过网关）

适用于本地调试和测试脚本，直接向指定 subject 发送 request 并接收响应。

CLI 使用方式::

    # 携带 JSON payload 发送请求
    chongming request user.register --data '{"email": "test@example.com", "password": "123456"}'

    # 从文件读取 payload
    chongming request user.register --file payload.json

    # 美化输出
    chongming request user.register --data '{"email": "test@example.com"}' --pretty

    # 指定超时
    chongming request user.login --data '{"email": "test@example.com"}' --timeout 10

    # 通过 stdin 传递 payload（管道）
    echo '{"email": "test@example.com"}' | chongming request user.register

测试脚本使用方式::

    import asyncio
    from chongming_cli.commands.request import send_request

    async def main():
        result = await send_request(
            "user.register",
            {"email": "test@example.com", "password": "123456"},
            timeout=10,
        )
        print(result)

    asyncio.run(main())
"""

import argparse
import asyncio
import json
import ssl
import sys
from typing import Any, Dict, Optional

import nats
import nats.errors

# ── ANSI 颜色代码 ─────────────────────────────────────────────────────
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_WHITE = "\033[37m"
_RESET = "\033[0m"


# ══════════════════════════════════════════════════════════════════════
# 参数解析
# ══════════════════════════════════════════════════════════════════════

def add_request_parser(subparsers):
    """注册 request 子命令的参数解析器"""
    parser = subparsers.add_parser(
        "request",
        help="直接向 NATS subject 发送请求（绕过网关）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 携带 JSON payload 发送请求
  chongming request user.register --data '{"email": "test@example.com", "password": "123456"}'

  # 从文件读取 payload
  chongming request user.register --file payload.json

  # 美化输出
  chongming request user.register --data '{"email": "test@example.com"}' --pretty

  # 通过 stdin 管道传入
  echo '{"email": "test@example.com"}' | chongming request user.register

  # 自定义 NATS 连接
  chongming request user.register --data '{"email": "test@example.com"}' --host nats.example.com --port 4222

  # 使用凭证连接
  chongming request user.register --data '{"email": "test@example.com"}' --creds ./nats.creds
        """,
    )
    parser.add_argument(
        "subject",
        type=str,
        help='要请求的业务主题，如 user.register',
    )
    parser.add_argument(
        "--data", "-d",
        type=str,
        default=None,
        help="请求 JSON payload（字符串）",
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="从文件读取请求 payload（JSON）",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=10.0,
        help="请求超时秒数（默认 10 秒）",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="美化输出响应 JSON",
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


# ══════════════════════════════════════════════════════════════════════
# 命令入口
# ══════════════════════════════════════════════════════════════════════

def handle_request(args):
    """处理 request 命令的同步入口"""
    asyncio.run(_run_request(args))


async def _run_request(args):
    """异步主逻辑"""

    # ── 读取 payload ──────────────────────────────────────────────────
    payload_data = None

    if args.file:
        try:
            with open(args.file, "r") as f:
                payload_data = json.loads(f.read())
        except FileNotFoundError:
            print(f"{_RED}错误:{_RESET} 文件不存在: {args.file}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"{_RED}错误:{_RESET} 文件 JSON 解析失败: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.data:
        try:
            payload_data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"{_RED}错误:{_RESET} --data JSON 解析失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # 尝试从 stdin 读取
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read().strip()
            if stdin_data:
                try:
                    payload_data = json.loads(stdin_data)
                except json.JSONDecodeError as e:
                    print(f"{_RED}错误:{_RESET} stdin JSON 解析失败: {e}", file=sys.stderr)
                    sys.exit(1)

    if payload_data is None:
        print(f"{_RED}错误:{_RESET} 未提供 payload，使用 --data、--file 或管道传入",
              file=sys.stderr)
        sys.exit(1)

    # ── 连接 NATS ─────────────────────────────────────────────────────
    urls = f"nats://{args.host}:{args.port}"

    opts: Dict[str, Any] = {
        "servers": [urls],
        "name": "chongming-request",
        "connect_timeout": 10,
    }

    if args.user and args.password:
        opts["user"] = args.user
        opts["password"] = args.password
    if args.token:
        opts["token"] = args.token
    if args.creds:
        opts["user_credentials"] = args.creds
    if args.nkey:
        opts["nkeys_seed"] = args.nkey

    if args.tls or args.tls_cert or args.tls_key or args.tls_ca:
        ssl_ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if args.tls_ca:
            ssl_ctx.load_verify_locations(cafile=args.tls_ca)
        if args.tls_cert and args.tls_key:
            ssl_ctx.load_cert_chain(certfile=args.tls_cert, keyfile=args.tls_key)
        opts["tls"] = ssl_ctx

    nc = None
    try:
        print(f"{_DIM}正在连接 NATS: {urls}{_RESET}", file=sys.stderr)
        nc = await nats.connect(**opts)
        print(f"{_GREEN}已连接到 NATS{_RESET}", file=sys.stderr)
        print(file=sys.stderr)
    except Exception as e:
        print(f"{_RED}连接 NATS 失败:{_RESET} {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = await _do_request(
            nc, args.subject, payload_data, timeout=args.timeout
        )
        if args.pretty:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(json.dumps(result, ensure_ascii=False, default=str))
    except asyncio.TimeoutError:
        print(f"{_RED}请求超时{_RESET} ({args.timeout}s)", file=sys.stderr)
        sys.exit(1)
    except nats.errors.BadSubjectError:
        print(f"{_RED}错误:{_RESET} 无效的 subject: {args.subject}", file=sys.stderr)
        sys.exit(1)
    except nats.errors.NoRespondersError:
        print(f"{_RED}错误:{_RESET} 没有 Worker 订阅该 subject: {args.subject}",
              file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"{_RED}请求失败:{_RESET} {e}", file=sys.stderr)
        sys.exit(1)
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


# ══════════════════════════════════════════════════════════════════════
# 核心请求函数（可供测试脚本导入使用）
# ══════════════════════════════════════════════════════════════════════

async def send_request(
    subject: str,
    payload: Dict[str, Any],
    host: str = "localhost",
    port: int = 4222,
    timeout: float = 10.0,
    token: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    creds: Optional[str] = None,
    nkey: Optional[str] = None,
    tls: bool = False,
    tls_ca: Optional[str] = None,
    tls_cert: Optional[str] = None,
    tls_key: Optional[str] = None,
) -> Dict[str, Any]:
    """向 NATS subject 发送请求并返回响应（适用于测试脚本）

    使用示例::

        import asyncio
        from chongming_cli.commands.request import send_request

        async def test_register():
            result = await send_request(
                "user.register",
                {"email": "test@example.com", "password": "123456"},
                timeout=10,
            )
            assert result["code"] == 200

        asyncio.run(test_register())

    :param subject: NATS 业务主题
    :param payload: 请求数据 dict
    :param host: NATS 服务器地址
    :param port: NATS 服务器端口
    :param timeout: 请求超时秒数
    :param token: NATS 认证令牌
    :param user: NATS 用户名
    :param password: NATS 密码
    :param creds: NATS 用户凭证文件路径
    :param nkey: NKEY 种子文件路径
    :param tls: 是否启用 TLS
    :param tls_ca: TLS CA 证书路径
    :param tls_cert: TLS 客户端证书路径
    :param tls_key: TLS 客户端密钥路径
    :return: 响应数据 dict
    :raises asyncio.TimeoutError: 请求超时
    :raises nats.errors.NoRespondersError: 没有 Worker 订阅该 subject
    """
    opts: Dict[str, Any] = {
        "servers": [f"nats://{host}:{port}"],
        "name": "chongming-request",
        "connect_timeout": 10,
    }

    if user and password:
        opts["user"] = user
        opts["password"] = password
    if token:
        opts["token"] = token
    if creds:
        opts["user_credentials"] = creds
    if nkey:
        opts["nkeys_seed"] = nkey

    if tls or tls_cert or tls_key or tls_ca:
        ssl_ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if tls_ca:
            ssl_ctx.load_verify_locations(cafile=tls_ca)
        if tls_cert and tls_key:
            ssl_ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
        opts["tls"] = ssl_ctx

    nc = await nats.connect(**opts)
    try:
        return await _do_request(nc, subject, payload, timeout=timeout)
    finally:
        if nc.is_connected:
            try:
                await nc.drain()
            except Exception:
                pass
            try:
                await nc.close()
            except Exception:
                pass


async def _do_request(
    nc,
    subject: str,
    payload: Dict[str, Any],
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """执行一次 NATS request 并解析响应"""
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
    resp = await nc.request(subject, payload_bytes, timeout=timeout)
    return json.loads(resp.data.decode())