"""
chongming log-export 命令 - 从 MinIO 导出指定 worker/gateway 的日志

从 MinIO 对象存储中按条件查询并导出日志，支持：

- 按服务类型筛选（gateway / worker）
- 按服务实例名称筛选（如 api-gateway-1、example-worker）
- 按时间范围筛选（起始/结束时间）
- 按日志级别筛选
- 输出为 JSON 或文本格式

使用方式::

    # 导出所有 gateway 日志
    chongming log-export --type gateway

    # 导出指定 worker 的日志，最近 1 小时
    chongming log-export --type worker --name example-worker --since "1h"

    # 导出指定时间范围内的日志
    chongming log-export --type gateway --name api-gateway-1 \\
        --start "2026-05-28T00:00:00Z" --end "2026-05-29T00:00:00Z"

    # 导出 DEBUG 及以上级别的日志，输出为 JSON
    chongming log-export --type worker --name example --level DEBUG --format json

    # 列出 MinIO 中所有可用的服务实例
    chongming log-export --list-services

    # 查看 MinIO 日志存储统计
    chongming log-export --stats
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Iterator

from minio import Minio
from minio.error import S3Error


# ── 默认 MinIO 连接配置 ───────────────────────────────────────────────
DEFAULT_ENDPOINT = "localhost:9000"
DEFAULT_ACCESS_KEY = "minioadmin"
DEFAULT_SECRET_KEY = "minioadmin"
DEFAULT_BUCKET = "chongming-logs"
DEFAULT_SECURE = False


def _parse_time_range(
    since: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """解析时间范围参数

    支持:
    - --since "1h" / "30m" / "7d"（相对当前时间）
    - --start "2026-05-28T00:00:00Z" / "2026-05-28 00:00:00"
    - --end "2026-05-29T00:00:00Z"

    :return: (start_time, end_time)，为 None 表示不限制
    """
    start_time = None
    end_time = None

    if since:
        # 解析相对时间
        match = re.match(r"^(\d+)([smhd])$", since)
        if not match:
            raise ValueError(f"无效的 --since 格式: '{since}'，请使用如 1h、30m、7d")

        value = int(match.group(1))
        unit = match.group(2)
        now = datetime.now(timezone.utc)

        if unit == "s":
            start_time = now - timedelta(seconds=value)
        elif unit == "m":
            start_time = now - timedelta(minutes=value)
        elif unit == "h":
            start_time = now - timedelta(hours=value)
        elif unit == "d":
            start_time = now - timedelta(days=value)

    if start:
        start_time = _parse_datetime(start)

    if end:
        end_time = _parse_datetime(end)

    return start_time, end_time


def _parse_datetime(s: str) -> datetime:
    """解析日期时间字符串"""
    # 尝试多种格式
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间字符串: '{s}'")


def _connect_minio(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool,
    bucket: Optional[str] = None,
) -> Minio:
    """连接 MinIO

    :param endpoint: MinIO 地址 (例如 localhost:9000)
    :param access_key: 访问密钥
    :param secret_key: 密钥
    :param secure: 是否使用 TLS
    :param bucket: 目标存储桶名称，如果指定且不存在则自动创建
    :return: MinIO 客户端
    """
    try:
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        # 测试连接
        client.list_buckets()

        # 检查并自动创建目标桶（如果不存在）
        if bucket and not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"提示: 已自动创建 MinIO 存储桶 '{bucket}'", file=sys.stderr)

        return client
    except S3Error as e:
        print(f"错误: MinIO 连接失败 ({endpoint}): {e.message}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: 无法连接到 MinIO ({endpoint}): {e}", file=sys.stderr)
        sys.exit(1)


def _list_services(client: Minio, bucket: str) -> dict:
    """列出 MinIO 中所有可用的服务实例

    遍历日志路径格式：logs/{service_type}/{service_name}/...

    :return: {service_type: [service_name, ...]}
    """
    services = {}

    try:
        # 列出 logs/ 下的所有前缀（即 service_type 层）
        # recursive=False 时 list_objects 内部使用 '/' 作为分隔符，返回的 Object 中 is_dir=True 的即为目录前缀
        objects = client.list_objects(bucket, prefix="logs/", recursive=False)

        for obj in objects:
            # obj.object_name 格式: "logs/gateway/" 或 "logs/worker/"
            prefix = obj.object_name.rstrip("/") # type: ignore
            service_type = prefix.split("/")[-1]

            if service_type not in services:
                services[service_type] = []

            # 列出该类型下的所有实例（service_name 层）
            type_prefix = f"{prefix}/"
            type_objects = client.list_objects(
                bucket, prefix=type_prefix, recursive=False
            )

            for tobj in type_objects:
                name_prefix = tobj.object_name.rstrip("/") # type: ignore
                service_name = name_prefix.split("/")[-1]
                services[service_type].append(service_name)

    except S3Error as e:
        print(f"警告: 列出服务失败: {e.message}", file=sys.stderr)

    return services


def _get_log_objects(
    client: Minio,
    bucket: str,
    service_type: Optional[str],
    service_name: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    level: Optional[str],
) -> Iterator[dict]:
    """获取符合条件的日志对象

    按顺序遍历 MinIO 对象，支持按路径过滤和时间范围过滤。

    :yield: 每条日志的字典
    """
    # 构建搜索前缀
    prefix_parts = ["logs"]
    if service_type:
        prefix_parts.append(service_type)
        if service_name:
            prefix_parts.append(service_name)

    prefix = "/".join(prefix_parts) + "/" if len(prefix_parts) > 1 else "logs/"

    try:
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
    except S3Error as e:
        print(f"错误: 列出日志对象失败: {e.message}", file=sys.stderr)
        return

    total_objects = 0
    total_lines = 0

    for obj in objects:
        obj_name = obj.object_name

        # 按时间范围过滤（从对象路径中解析日期）
        if start_time or end_time:
            obj_time = _parse_object_time(obj_name) # type: ignore
            if obj_time:
                if start_time and obj_time < start_time:
                    continue
                if end_time and obj_time > end_time:
                    # 由于对象按时间排序，超过 end_time 后可提前退出
                    pass

        # 读取并解析日志
        try:
            data = client.get_object(bucket, obj_name) # type: ignore
            raw = data.read()
            data.close()

            # 解压 if gzipped
            if obj_name.endswith(".gz"): # type: ignore
                content = gzip.decompress(raw).decode("utf-8")
            else:
                content = raw.decode("utf-8")

            total_objects += 1

            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = {"raw_message": line, "level": "UNKNOWN"}

                # 按日志级别过滤
                if level and entry.get("level", "").upper() != level.upper():
                    continue

                total_lines += 1
                yield entry

        except S3Error as e:
            print(f"警告: 读取对象失败 {obj_name}: {e.message}", file=sys.stderr)
            continue

    print(f"  已扫描 {total_objects} 个日志文件，共 {total_lines} 条日志", file=sys.stderr)


def _parse_object_time(object_name: str) -> Optional[datetime]:
    """从 MinIO 对象路径中解析时间

    路径格式: logs/{type}/{name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log[.gz]
    """
    parts = object_name.split("/")
    if len(parts) >= 7:
        try:
            year, month, day, hour = (
                int(parts[3]),
                int(parts[4]),
                int(parts[5]),
                int(parts[6]),
            )
            return datetime(year, month, day, hour, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            pass
    return None


def _print_log(entry: dict, fmt: str, show_meta: bool):
    """输出一条日志

    :param entry: 日志字典
    :param fmt: 输出格式 (json / text)
    :param show_meta: 是否显示元数据字段
    """
    if fmt == "json":
        if show_meta:
            print(json.dumps(entry, ensure_ascii=False, default=str))
        else:
            # 只输出核心字段
            slim = {
                "timestamp": entry.get("timestamp", ""),
                "level": entry.get("level", ""),
                "service": f"{entry.get('service_type', '?')}/{entry.get('service_name', '?')}",
                "request_id": entry.get("request_id", "-"),
                "message": entry.get("message", ""),
            }
            print(json.dumps(slim, ensure_ascii=False, default=str))
    else:
        # text 格式
        ts = entry.get("timestamp", "")
        level = entry.get("level", "UNKNOWN").ljust(5)
        svc = f"{entry.get('service_type', '?')}/{entry.get('service_name', '?')}"
        rid = entry.get("request_id", "-")
        msg = entry.get("message", entry.get("raw_message", ""))

        if show_meta:
            logger = entry.get("logger", "")
            module = entry.get("module", "")
            line = entry.get("line", "")
            extra = f" [{logger}] ({module}:{line})"
        else:
            extra = ""

        print(f"{ts} [{level}] [{rid}] {svc}: {msg}{extra}")


def _show_stats(client: Minio, bucket: str):
    """显示 MinIO 日志存储统计"""
    print("MinIO 日志存储统计")
    print("=" * 60)

    try:
        # 获取桶信息
        total_size = 0
        total_objects = 0
        type_stats = {}

        objects = client.list_objects(bucket, prefix="logs/", recursive=True)
        for obj in objects:
            total_objects += 1
            total_size += obj.size # type: ignore

            # 解析路径获取服务类型和名称
            parts = obj.object_name.split("/") # type: ignore
            if len(parts) >= 4:
                svc_type = parts[1]
                svc_name = parts[2]
                key = f"{svc_type}/{svc_name}"
                if key not in type_stats:
                    type_stats[key] = {"objects": 0, "size": 0}
                type_stats[key]["objects"] += 1
                type_stats[key]["size"] += obj.size

        print(f"  桶名称:      {bucket}")
        print(f"  总对象数:    {total_objects}")
        print(f"  总大小:      {_format_size(total_size)}")
        print()

        if type_stats:
            print("按服务实例统计:")
            print(f"  {'服务':<30} {'对象数':<10} {'大小':<12}")
            print(f"  {'-'*30} {'-'*10} {'-'*12}")
            for key in sorted(type_stats.keys()):
                s = type_stats[key]
                print(f"  {key:<30} {s['objects']:<10} {_format_size(s['size']):<12}")

    except S3Error as e:
        print(f"错误: 获取统计失败: {e.message}", file=sys.stderr)


def _format_size(size_bytes: int) -> str:
    """格式化字节大小为人类可读格式"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.2f} GB"


# ── 参数解析 ──────────────────────────────────────────────────────────


def add_log_export_parser(subparsers):
    parser = subparsers.add_parser(
        "log-export",
        help="从 MinIO 导出指定 worker/gateway 的日志",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出 MinIO 中所有可导出的服务实例
  chongming log-export --list-services

  # 导出所有 gateway 日志
  chongming log-export --type gateway

  # 导出指定 worker 最近 1 小时的日志
  chongming log-export --type worker --name example --since 1h

  # 导出指定时间范围 Gateway-1 的日志
  chongming log-export --type gateway --name api-gateway-1 \\
      --start "2026-05-28T00:00:00Z" --end "2026-05-29T00:00:00Z"

  # 导出 DEBUG 级别日志，JSON 格式
  chongming log-export --type worker --name example --level DEBUG --format json

  # 带元数据字段导出
  chongming log-export --type gateway --show-meta

  # 保存到文件
  chongming log-export --type worker --name example --since 2h \\
      --output /tmp/example-logs.json

  # 查看日志存储统计
  chongming log-export --stats

  # 自定义 MinIO 连接
  chongming log-export --type gateway \\
      --minio-endpoint minio-cluster:9000 \\
      --minio-access-key mykey --minio-secret-key mysecret \\
      --bucket my-logs

MinIO 日志路径结构:
  logs/{service_type}/{service_name}/{YYYY}/{MM}/{DD}/{HH}/{uuid}.log[.gz]
  例如: logs/worker/example-worker/2026/05/28/14/abc123.log.gz
        """,
    )
    # 筛选参数
    filter_group = parser.add_argument_group("筛选条件")
    filter_group.add_argument(
        "--type",
        choices=["gateway", "worker"],
        help="服务类型：gateway 或 worker",
    )
    filter_group.add_argument(
        "--name",
        type=str,
        help="服务实例名称（例如 api-gateway-1、example-worker）",
    )
    filter_group.add_argument(
        "--level",
        type=str,
        default=None,
        help="日志级别过滤（DEBUG/INFO/WARNING/ERROR/CRITICAL，不区分大小写）",
    )

    # 时间范围参数
    time_group = parser.add_argument_group("时间范围")
    time_group.add_argument(
        "--since",
        type=str,
        help="相对时间范围（例如 1h、30m、7d）",
    )
    time_group.add_argument(
        "--start",
        type=str,
        help="起始时间（ISO 格式，例如 2026-05-28T00:00:00Z）",
    )
    time_group.add_argument(
        "--end",
        type=str,
        help="结束时间（ISO 格式，例如 2026-05-29T00:00:00Z）",
    )

    # 输出参数
    output_group = parser.add_argument_group("输出选项")
    output_group.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text）",
    )
    output_group.add_argument(
        "--show-meta",
        action="store_true",
        help="显示元数据字段（logger、module、line 等）",
    )
    output_group.add_argument(
        "--output", "-o",
        type=str,
        help="输出到文件（默认输出到 stdout）",
    )

    # MinIO 连接参数
    minio_group = parser.add_argument_group("MinIO 连接")
    minio_group.add_argument(
        "--minio-endpoint",
        type=str,
        default=os.environ.get("MINIO_ENDPOINT", DEFAULT_ENDPOINT),
        help=f"MinIO 地址（默认 {DEFAULT_ENDPOINT}，也可通过 MINIO_ENDPOINT 环境变量设置）",
    )
    minio_group.add_argument(
        "--minio-access-key",
        type=str,
        default=os.environ.get("MINIO_ACCESS_KEY", DEFAULT_ACCESS_KEY),
        help=f"MinIO 访问密钥（默认 {DEFAULT_ACCESS_KEY}，也可通过 MINIO_ACCESS_KEY 环境变量设置）",
    )
    minio_group.add_argument(
        "--minio-secret-key",
        type=str,
        default=os.environ.get("MINIO_SECRET_KEY", DEFAULT_SECRET_KEY),
        help=f"MinIO 密钥（默认 {DEFAULT_SECRET_KEY}，也可通过 MINIO_SECRET_KEY 环境变量设置）",
    )
    minio_group.add_argument(
        "--minio-secure",
        action="store_true",
        default=os.environ.get("MINIO_SECURE", "false").lower() == "true",
        help="MinIO 启用 TLS（默认不启用，也可通过 MINIO_SECURE 环境变量设置）",
    )
    minio_group.add_argument(
        "--bucket",
        type=str,
        default=os.environ.get("MINIO_LOG_BUCKET", DEFAULT_BUCKET),
        help=f"存储桶名称（默认 {DEFAULT_BUCKET}，也可通过 MINIO_LOG_BUCKET 环境变量设置）",
    )

    # 特殊模式
    special_group = parser.add_argument_group("特殊模式")
    special_group.add_argument(
        "--list-services",
        action="store_true",
        help="列出 MinIO 中所有可用的服务实例",
    )
    special_group.add_argument(
        "--stats",
        action="store_true",
        help="显示 MinIO 日志存储统计信息",
    )


def handle_log_export(args):
    """处理 log-export 命令"""
    # 连接 MinIO（自动创建目标桶如果不存在）
    client = _connect_minio(
        args.minio_endpoint,
        args.minio_access_key,
        args.minio_secret_key,
        args.minio_secure,
        bucket=args.bucket,
    )

    # 特殊模式：列出服务
    if args.list_services:
        print("MinIO 中可用的服务实例:")
        print("=" * 60)
        services = _list_services(client, args.bucket)
        if not services:
            print("  (没有找到日志数据)")
            return

        for svc_type in sorted(services.keys()):
            names = services[svc_type]
            print(f"\n{svc_type.upper()} ({len(names)} 个实例):")
            for name in sorted(names):
                print(f"  - {name}")
        return

    # 特殊模式：统计
    if args.stats:
        _show_stats(client, args.bucket)
        return

    # 验证筛选条件
    if not args.type and not args.name:
        print("错误: 至少需要指定 --type 或 --name 筛选条件", file=sys.stderr)
        print("提示: 使用 --list-services 查看可用的服务实例", file=sys.stderr)
        sys.exit(1)

    # 解析时间范围
    try:
        start_time, end_time = _parse_time_range(args.since, args.start, args.end)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 构建查询描述信息
    query_desc = []
    if args.type:
        query_desc.append(f"type={args.type}")
    if args.name:
        query_desc.append(f"name={args.name}")
    if args.level:
        query_desc.append(f"level={args.level}")
    if start_time:
        query_desc.append(f"since={start_time.isoformat()}")
    if end_time:
        query_desc.append(f"until={end_time.isoformat()}")
    query_str = ", ".join(query_desc)

    print(f"查询日志: {query_str}", file=sys.stderr)
    print(file=sys.stderr)

    # 打开输出文件（如果指定）
    output_file = None
    if args.output:
        try:
            output_file = open(args.output, "w", encoding="utf-8")
            print(f"输出到文件: {args.output}", file=sys.stderr)
        except IOError as e:
            print(f"错误: 无法打开输出文件 {args.output}: {e}", file=sys.stderr)
            sys.exit(1)

    # 查询并输出日志
    count = 0
    try:
        for entry in _get_log_objects(
            client,
            args.bucket,
            args.type,
            args.name,
            start_time,
            end_time,
            args.level,
        ):
            # 输出
            if output_file:
                # 写入文件
                _write_log_to_file(output_file, entry, args.format, args.show_meta)
            else:
                _print_log(entry, args.format, args.show_meta)
            count += 1

    except KeyboardInterrupt:
        print(file=sys.stderr)
        print("导出被中断", file=sys.stderr)
    finally:
        if output_file:
            output_file.close()

    print(file=sys.stderr)
    print(f"导出完成：共 {count} 条日志", file=sys.stderr)


def _write_log_to_file(f, entry: dict, fmt: str, show_meta: bool):
    """将日志写入文件

    JSON 格式写入一个 JSON 数组行，text 格式每行一条日志。
    """
    if fmt == "json":
        if show_meta:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        else:
            slim = {
                "timestamp": entry.get("timestamp", ""),
                "level": entry.get("level", ""),
                "service": f"{entry.get('service_type', '?')}/{entry.get('service_name', '?')}",
                "request_id": entry.get("request_id", "-"),
                "message": entry.get("message", ""),
            }
            f.write(json.dumps(slim, ensure_ascii=False, default=str) + "\n")
    else:
        ts = entry.get("timestamp", "")
        level = entry.get("level", "UNKNOWN").ljust(5)
        svc = f"{entry.get('service_type', '?')}/{entry.get('service_name', '?')}"
        rid = entry.get("request_id", "-")
        msg = entry.get("message", entry.get("raw_message", ""))

        if show_meta:
            logger = entry.get("logger", "")
            module = entry.get("module", "")
            line = entry.get("line", "")
            extra = f" [{logger}] ({module}:{line})"
        else:
            extra = ""

        f.write(f"{ts} [{level}] [{rid}] {svc}: {msg}{extra}\n")
