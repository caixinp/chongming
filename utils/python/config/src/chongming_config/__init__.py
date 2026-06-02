"""
Chongming Configuration Parser
===============================

支持标准 TOML 配置加载，并提供向后兼容的配置解析。
新增功能：
- 响应模型的 field->type/required/default 字段名语法
- params 扩展类型支持 list[int], datetime, Optional[str] 等
- [registration.defaults] 默认值继承
- config_version 版本管理
"""

import logging
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, TypedDict, Union, get_type_hints

import tomli

logger = logging.getLogger("chongming.config")

# ────────────────────────────────────────────────────────────
# 类型常量
# ────────────────────────────────────────────────────────────

# 内部支持的 BaseType（扩展类型在 load 时解析为完整类型字符串）
SIMPLE_TYPES = frozenset({"str", "int", "float", "bool", "list", "dict", "object", "any"})

COMPLEX_TYPE_PATTERN = re.compile(
    r"^(?P<base>list|dict|Optional)\[(?P<inner>.+)\]$"
)

# ────────────────────────────────────────────────────────────
# 配置 TypedDict 定义（供类型提示使用）
# ────────────────────────────────────────────────────────────


class FieldDef(TypedDict, total=False):
    """单个字段定义（新响应模型语法）

    旧语法: field = ["type", "default_or_required", nested?]
    新语法: field = { type = "str", required = true, default = "...", fields = { ... } }
    """
    type: str
    required: bool
    default: Any
    fields: Dict[str, Any]  # 嵌套字段


class RegistrationItemConfig(TypedDict, total=False):
    subject: str
    method: str
    path: str
    summary: str
    docstring: str
    params: List[str]
    ttl: int
    timeout: float
    response_model: Dict[str, Any]  # 可以是旧列表格式或新字段定义格式
    response_model_format: str  # "legacy" | "new"
    auth_required: bool
    shared: bool
    internal: bool


class RegistrationDefaults(TypedDict, total=False):
    """默认值配置节"""
    method: str
    ttl: int
    timeout: float
    auth_required: bool
    shared: bool
    tags: List[str]


class RegistrationConfig(TypedDict, total=False):
    type: str
    service: str
    router_prefix: str
    tags: List[str]
    items: List[RegistrationItemConfig]
    defaults: RegistrationDefaults
    heartbeat_interval: int
    config_version: str  # 新增：配置版本号


class WorkerConfig(TypedDict, total=False):
    name: str
    version: str
    description: str
    config_version: str  # 新增：配置版本号


class NATSConfig(TypedDict):
    urls: List[str]


class MinioLoggingConfig(TypedDict, total=False):
    enabled: bool
    endpoint: str
    bucket: str
    retention_days: int
    level: int


class LoggingConfig(TypedDict, total=False):
    minio: MinioLoggingConfig


class Config(TypedDict, total=False):
    worker: WorkerConfig
    nats: NATSConfig
    registration: RegistrationConfig
    logging: LoggingConfig


class DefaultConfig(TypedDict, total=False):
    debug: bool
    description: str
    name: str
    version: str
    env: str
    prefix: str


class DatabaseMasterConfig(TypedDict, total=False):
    host: str
    port: str
    username: str
    password: str


class DatabaseSlaveConfig(TypedDict, total=False):
    host: str
    port: str
    username: str
    password: str


class DataBaseConfig(TypedDict, total=False):
    type: str
    master: DatabaseMasterConfig
    slave: DatabaseSlaveConfig


class CleanupConfig(TypedDict, total=False):
    interval: int


class JWTConfig(TypedDict, total=False):
    enabled: bool
    algorithm: str
    secret_key: str
    issuer: str
    audience: str
    user_id_claim: str
    roles_claim: str
    whitelist_paths: List[str]


class GatewayConfig(TypedDict, total=False):
    default: DefaultConfig
    nats: NATSConfig
    database: DataBaseConfig
    cleanup: CleanupConfig
    logging: LoggingConfig
    jwt: JWTConfig


# ────────────────────────────────────────────────────────────
# 核心加载函数
# ────────────────────────────────────────────────────────────


def load_config(config_path: str) -> Config:
    """从 TOML 文件加载配置（Worker 专用）

    特性：
    - 自动合并 [registration.defaults] 到每个 items
    - 自动解析 response_model 新旧语法
    - 支持扩展类型注解（list[int], datetime 等）
    """
    with open(config_path, "rb") as f:
        config = tomli.load(f)

    config = _deep_normalize(config)
    config = _apply_defaults(config)

    if "registration" in config:
        config["registration"] = _normalize_registration(config["registration"])
    if "logging" in config:
        config["logging"] = _normalize_logging(config["logging"])

    return config  # type: ignore


def load_gateway_config(config_path: str) -> GatewayConfig:
    """从 TOML 文件加载配置（Gateway 专用）"""
    with open(config_path, "rb") as f:
        config = tomli.load(f)
    return config  # type: ignore


# ────────────────────────────────────────────────────────────
# 归一化处理：统一 key 命名风格
# ────────────────────────────────────────────────────────────


def _deep_normalize(config: Any) -> Any:
    """递归将 TOML 中 '-' 命名转为 '_' 命名（驼峰）"""
    if isinstance(config, dict):
        return {k.replace("-", "_"): _deep_normalize(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_deep_normalize(item) for item in config]
    return config


# ────────────────────────────────────────────────────────────
# Defaults 继承
# ────────────────────────────────────────────────────────────


def _apply_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """将 [registration.defaults] 合并到每个 items 中

    rules:
    - 只合并 items 中未显式指定的字段
    - 不合并 subject、path（必须每个 item 独立指定）
    - 保留 defaults 在 registration 中，以便发送到网关用于路由恢复
    """
    registration = config.get("registration")
    if not registration or not isinstance(registration, dict):
        return config

    defaults = registration.get("defaults", {})
    items = registration.get("items", [])
    if not defaults or not items:
        return config

    skip_keys = {"subject", "path", "docstring", "summary", "params", "response_model"}

    merged_items = []
    for item in items:
        if not isinstance(item, dict):
            merged_items.append(item)
            continue
        merged = {**defaults}
        # defaults 中移除不应继承的 key
        for sk in skip_keys:
            merged.pop(sk, None)
        # item 显式指定的覆盖 defaults
        merged.update(item)
        merged_items.append(merged)

    registration["items"] = merged_items
    # ⚠️ 保留 defaults 不删除，以便后续 NATS 消息携带给网关使用
    # 网关的 _handle_register / _handle_batch_heartbeat 会读取 defaults
    # 用于 item 未指定 method/ttl/timeout 时的 fallback
    return config


# ────────────────────────────────────────────────────────────
# Registration 归一化处理
# ────────────────────────────────────────────────────────────


def _normalize_registration(registration: Dict[str, Any]) -> Dict[str, Any]:
    """归一化 registration 配置

    1. 给每个 item 加上 response_model_format 标记
    2. 解析扩展参数类型（list[int] 等）
    3. 验证 config_version 兼容性
    """
    items = registration.get("items", [])
    normalized_items = []

    for item in items:
        if isinstance(item, dict):
            item = _normalize_item(item)
        normalized_items.append(item)

    registration["items"] = normalized_items

    # 版本校验
    _check_config_version(registration)

    return registration


def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """归一化单个 item

    - 检测 response_model 格式（新旧语法）
    - 扩展 params 类型解析
    """
    item = _detect_response_model_format(item)
    item = _normalize_response_model(item)
    item = _normalize_params(item)
    return item


def _detect_response_model_format(item: Dict[str, Any]) -> Dict[str, Any]:
    """检测 response_model 是旧语法还是新语法"""
    response_model = item.get("response_model")
    if not response_model or not isinstance(response_model, dict):
        item["response_model_format"] = "none"
        return item

    # 新语法：值是 dict 且包含 "type" 键
    is_new_format = False
    for val in response_model.values():
        if isinstance(val, dict) and "type" in val:
            is_new_format = True
            break

    if is_new_format:
        item["response_model_format"] = "new"
    else:
        item["response_model_format"] = "legacy"

    return item


def _normalize_response_model(item: Dict[str, Any]) -> Dict[str, Any]:
    """归一化 response_model：将新旧语法统一为内部标准格式

    新语法: { field = { type = "str", required = true, default = "...", fields = {...} } }
    旧语法: { field = ["type", "default_or_required", nested?] }

    统一为内部格式: { field = { type: str, required: bool, default: any, fields: dict } }
    """
    response_model = item.get("response_model")
    fmt = item.get("response_model_format")

    if not response_model or fmt == "none":
        return item

    normalized = {}
    for field_name, field_def in response_model.items():
        if fmt == "new":
            # 新语法：验证并补全
            if isinstance(field_def, dict):
                normalized[field_name] = _normalize_field_def_new(field_def)
            else:
                # 降级为旧语法
                normalized[field_name] = _normalize_field_def_legacy(field_def)
        else:
            # 旧语法
            normalized[field_name] = _normalize_field_def_legacy(field_def)

    item["response_model"] = normalized
    return item


def _normalize_field_def_new(field_def: Dict[str, Any]) -> Dict[str, Any]:
    """归一化新语法字段定义"""
    result: Dict[str, Any] = {
        "type": field_def.get("type", "any"),
        "required": field_def.get("required", False),
        "default": field_def.get("default", None),
    }

    # 处理嵌套字段
    if "fields" in field_def and isinstance(field_def["fields"], dict):
        nested_fields = {}
        for nk, nv in field_def["fields"].items():
            if isinstance(nv, dict) and "type" in nv:
                nested_fields[nk] = _normalize_field_def_new(nv)
            else:
                nested_fields[nk] = _normalize_field_def_legacy(nv)
        result["fields"] = nested_fields

    return result


def _normalize_field_def_legacy(field_def: Any) -> Dict[str, Any]:
    """归一化旧语法字段定义

    旧语法: ["type", "default_or_required", nested_dict?]
    """
    result: Dict[str, Any] = {
        "type": "any",
        "required": False,
        "default": None,
        "fields": None,
    }

    if isinstance(field_def, list) and len(field_def) >= 2:
        result["type"] = str(field_def[0]) if field_def[0] else "any"
        default_raw = field_def[1]
        if default_raw == "__required__":
            result["required"] = True
        else:
            result["default"] = default_raw
        if len(field_def) > 2 and isinstance(field_def[2], dict):
            # 嵌套字段
            nested = {}
            for nk, nv in field_def[2].items():
                if isinstance(nv, list) and len(nv) >= 2:
                    nested[nk] = _normalize_field_def_legacy(nv)
                else:
                    nested[nk] = {
                        "type": "any",
                        "required": False,
                        "default": nv if nv != "__required__" else None,
                        "fields": None,
                    }
            result["fields"] = nested

    return result


def _normalize_params(item: Dict[str, Any]) -> Dict[str, Any]:
    """扩展 params 类型解析

    支持格式:
    - 基础: "user_id: str", "count: int"
    - 泛型: "tags: list[str]", "scores: list[int]", "meta: dict[str,Any]"
    - 可选: "name: Optional[str]"
    - 日期: "created_at: datetime"
    """
    params = item.get("params", [])
    if not params:
        return item

    normalized_params = []
    for param in params:
        if isinstance(param, str):
            normalized_params.append(_parse_param_type(param))
        else:
            normalized_params.append(param)

    item["params"] = normalized_params
    return item


def _parse_param_type(param_str: str) -> Dict[str, str]:
    """解析单个参数类型字符串

    "tags: list[str]" -> {"name": "tags", "raw_type": "list[str]", "py_type": "List[str]"}
    """
    parts = param_str.split(":", 1)
    name = parts[0].strip()
    raw_type = parts[1].strip() if len(parts) > 1 else "str"

    py_type = _resolve_python_type(raw_type)

    return {
        "name": name,
        "raw_type": raw_type,
        "py_type": py_type,
    }


def _resolve_python_type(raw_type: str) -> str:
    """将类型描述解析为 Python 类型注释字符串

    >>> _resolve_python_type("list[str]")
    "List[str]"
    >>> _resolve_python_type("datetime")
    "datetime"
    >>> _resolve_python_type("Optional[str]")
    "Optional[str]"
    """
    raw_type = raw_type.strip()

    # 简单类型
    if raw_type.lower() in SIMPLE_TYPES:
        return {
            "str": "str",
            "int": "int",
            "float": "float",
            "bool": "bool",
            "list": "list",
            "dict": "dict",
            "object": "dict",
            "any": "Any",
        }[raw_type.lower()]

    # 泛型: list[X], dict[K,V], Optional[X]
    m = COMPLEX_TYPE_PATTERN.match(raw_type)
    if m:
        base = m.group("base").capitalize()  # list → List, optional → Optional
        inner = m.group("inner").strip()
        # 递归解析 inner
        resolved_inner = _resolve_python_type(inner)
        return f"{base}[{resolved_inner}]"

    # 特殊类型
    special_types = {
        "datetime": "datetime",
        "any": "Any",
        "decimal": "Decimal",
    }
    if raw_type.lower() in special_types:
        return special_types[raw_type.lower()]

    # 未知类型，原样返回
    return raw_type


def _check_config_version(registration: Dict[str, Any]) -> None:
    """校验配置版本兼容性（Gateway 端使用）"""
    config_version = registration.get("config_version", "0.1")
    if config_version:
        logger.debug("Registration config_version: %s", config_version)


# ────────────────────────────────────────────────────────────
# Logging 归一化
# ────────────────────────────────────────────────────────────


def _normalize_logging(logging_config: Dict[str, Any]) -> Dict[str, Any]:
    """归一化 logging 配置"""
    minio_cfg = logging_config.get("minio", {})
    if isinstance(minio_cfg, dict):
        logging_config["minio"] = _normalize_minio_logging(minio_cfg)
    return logging_config


def _normalize_minio_logging(minio_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """归一化 MinIO logging 配置"""
    if "level" in minio_cfg and not isinstance(minio_cfg["level"], int):
        level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        minio_cfg["level"] = level_map.get(str(minio_cfg["level"]).upper(), 20)
    return minio_cfg


# ────────────────────────────────────────────────────────────
# 工具函数（生成模型时使用）
# ────────────────────────────────────────────────────────────


def get_field_def_type(field_def: Dict[str, Any]) -> str:
    """从归一化字段定义中获取类型字符串"""
    return field_def.get("type", "any")


def get_field_def_required(field_def: Dict[str, Any]) -> bool:
    """从归一化字段定义中获取是否必填"""
    return field_def.get("required", False)


def get_field_def_default(field_def: Dict[str, Any]) -> Any:
    """从归一化字段定义中获取默认值"""
    return field_def.get("default")


def get_field_def_fields(field_def: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从归一化字段定义中获取嵌套字段"""
    return field_def.get("fields")


# ────────────────────────────────────────────────────────────
# 兼容性：从旧语法列表提取信息的便捷函数
# ────────────────────────────────────────────────────────────


def legacy_field_type(legacy_field: list) -> str:
    """从旧语法列表中提取类型"""
    return str(legacy_field[0]) if len(legacy_field) > 0 else "any"


def legacy_field_default(legacy_field: list) -> Any:
    """从旧语法列表中提取默认值或 required 标记"""
    if len(legacy_field) > 1:
        raw = legacy_field[1]
        return raw if raw != "__required__" else None
    return None


def legacy_field_is_required(legacy_field: list) -> bool:
    """从旧语法列表中判断是否必填"""
    return len(legacy_field) > 1 and legacy_field[1] == "__required__"


def legacy_field_nested(legacy_field: list) -> Optional[Dict]:
    """从旧语法列表中提取嵌套字段"""
    return legacy_field[2] if len(legacy_field) > 2 and isinstance(legacy_field[2], dict) else None


# ────────────────────────────────────────────────────────────
# CLI 快速测试
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    config = load_config(path)
    logger.info("Loaded config from %s", path)
    import json
    print(json.dumps(config, indent=2, ensure_ascii=False, default=str))
