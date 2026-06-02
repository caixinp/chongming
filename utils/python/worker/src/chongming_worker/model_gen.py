"""
Pydantic Model Generator
=========================

从 config.toml 中定义的 handler 元数据，自动生成对应的 Pydantic 输入/输出模型类。

支持：
- 新旧两种 response_model 语法
- 扩展参数类型（list[int], datetime 等）
- 嵌套对象模型

使用方法::

    # 在 worker 根目录执行
    chongming gen-models example

    # 或在代码中直接调用
    from chongming_worker.model_gen import generate_models
    generate_models("workers/example")
"""

import os
import re
from typing import Any, Dict, List, Optional

from chongming_config import load_config
from chongming_config import (
    get_field_def_type,
    get_field_def_required,
    get_field_def_default,
    get_field_def_fields,
)

# ── Python 关键字/内置类型保留字，需要加后缀避免冲突 ────────────
_PYTHON_RESERVED = {
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
    "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "True", "False", "None", "type", "list", "dict", "str", "int",
    "float", "bool", "object", "input", "output", "model",
}

# 类型到 Python 类型别名的映射
_TYPE_ALIAS_MAP: Dict[str, str] = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "dict": "dict",
    "object": "dict",
    "any": "Any",
    "datetime": "datetime",
    "Decimal": "Decimal",
}

# ── 工具函数 ─────────────────────────────────────────────────────


def _sanitize_name(name: str) -> str:
    """清理名称：将包含特殊字符的字符串转为合法 Python 标识符"""
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    if not sanitized:
        sanitized = "_"
    if sanitized.lower() in _PYTHON_RESERVED:
        sanitized += "_"
    return sanitized


def _to_pascal_case(name: str) -> str:
    """将 snake_case 或 kebab-case 转为 PascalCase"""
    parts = re.split(r'[-_.\s]', name)
    return ''.join(part.capitalize() for part in parts if part)


def _resolve_type(type_str: str) -> str:
    """将类型字符串解析为 Python 类型注释

    >>> _resolve_type("list[str]")
    "List[str]"
    >>> _resolve_type("Optional[int]")
    "Optional[int]"
    >>> _resolve_type("datetime")
    "datetime"
    """
    type_str = type_str.strip()

    # 简单类型
    if type_str.lower() in _TYPE_ALIAS_MAP:
        return _TYPE_ALIAS_MAP[type_str.lower()]

    # 泛型: list[X], dict[K,V], Optional[X], List[X], Dict[K,V]
    m = re.match(r'^(?P<base>list|List|dict|Dict|Optional)\[(?P<inner>.+)\]$', type_str, re.IGNORECASE)
    if m:
        base = m.group("base")
        # 统一首字母大写 (list -> List, dict -> Dict)
        base_normalized = base[0].upper() + base[1:].lower() if base.lower() != "optional" else "Optional"
        inner = m.group("inner").strip()
        resolved_inner = _resolve_type(inner)
        return f"{base_normalized}[{resolved_inner}]"

    return type_str


def _format_default_value(raw: Any, type_str: str) -> str:
    """将默认值格式化为 Python 字面量

    支持：
    - 基本类型 int/float/str/bool
    - 复杂类型 list/dict
    """
    if raw is None:
        return "None"

    if isinstance(raw, bool):
        return str(raw).lower()

    if isinstance(raw, int):
        return str(raw)

    if isinstance(raw, float):
        return str(raw)

    if isinstance(raw, str):
        # 如果是 __required__ 标记，不应在此出现
        if raw == "__required__":
            return "None"
        return repr(raw)

    if isinstance(raw, list):
        # list 默认值：使用 Field(default_factory=list)
        return "None"  # 用 None 配合 Field 设置 default_factory

    if isinstance(raw, dict):
        # dict 默认值：使用 Field(default_factory=dict)
        return "None"

    return repr(str(raw))


# ── 核心生成函数 ─────────────────────────────────────────────────


def generate_models(worker_dir: str, shared_only: bool = False) -> str:
    """
    为指定的 worker 生成 Pydantic 模型代码

    :param worker_dir: worker 目录路径（包含 config.toml 的目录）
    :param shared_only: 如果为 True，只生成标记为 shared = true 的 handler 模型
    :return: 生成的 Python 代码字符串
    :raises FileNotFoundError: config.toml 不存在
    """
    config_path = os.path.join(worker_dir, "config.toml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.toml not found: {config_path}")

    config = load_config(config_path)
    items = config.get("registration", {}).get("items", [])

    if not items:
        return "# 没有注册的 handler，未生成模型\n"

    # 过滤：只保留 shared = true 的 item
    if shared_only:
        items = [item for item in items if item.get("shared") is True]
        if not items:
            return "# 没有标记为 shared=true 的 handler，未生成模型\n"

    lines: List[str] = []
    all_nested_models: Dict[str, List] = {}

    # 文件头
    lines.append('"""')
    lines.append("Pydantic Models - 自动生成")
    lines.append("")
    lines.append("生成自: config.toml")
    lines.append("指令: chongming gen-models")
    lines.append('"""')
    lines.append("")

    # imports
    lines.append("from datetime import datetime")
    lines.append("from typing import Any, Optional, List, Dict")
    lines.append("")
    lines.append("from pydantic import BaseModel, Field")
    lines.append("")

    for item in items:
        subject = item.get("subject", "")
        if not subject:
            continue

        subject_pascal = _to_pascal_case(subject)

        # ── 输入模型（基于 params） ────────────────────────
        params = item.get("params", [])
        input_fields = _extract_input_fields(params)

        input_model_name = f"{subject_pascal}Input"
        lines.append(f"class {input_model_name}(BaseModel):")
        lines.append(f"    \"\"\"{subject.upper()} 请求参数模型\"\"\"")
        if input_fields:
            for f_name, f_type, f_default in input_fields:
                cleaned_name = _sanitize_name(f_name)
                py_type = _resolve_type(f_type)
                if f_default is not None and f_default != "__required__":
                    # 有默认值
                    default_str = _format_default_value(f_default, f_type)
                    lines.append(f"    {cleaned_name}: {py_type} = {default_str}")
                else:
                    lines.append(f"    {cleaned_name}: {py_type}")
        else:
            lines.append("    pass")
        lines.append("")
        lines.append("")

        # ── 输出模型（基于 response_model） ────────────────
        response_model = item.get("response_model", {})
        fmt = item.get("response_model_format", "legacy")
        output_fields = []

        if isinstance(response_model, dict) and response_model:
            for field_name, field_def in response_model.items():
                if not isinstance(field_def, dict):
                    continue

                py_type_str = get_field_def_type(field_def)
                is_required = get_field_def_required(field_def)
                default_val = get_field_def_default(field_def)
                nested_fields = get_field_def_fields(field_def)

                if nested_fields and isinstance(nested_fields, dict):
                    # 嵌套对象 → 生成子模型
                    nested_name = _to_pascal_case(field_name)
                    nested_field_list = _extract_field_from_normalized(nested_fields)
                    all_nested_models[nested_name] = nested_field_list
                    output_fields.append((field_name, nested_name, is_required, default_val))
                else:
                    output_fields.append((field_name, py_type_str, is_required, default_val))

        output_model_name = f"{subject_pascal}Output"
        lines.append(f"class {output_model_name}(BaseModel):")
        lines.append(f"    \"\"\"{subject.upper()} 响应结果模型\"\"\"")
        if output_fields:
            for f_name, f_type, is_required, default_val in output_fields:
                cleaned_name = _sanitize_name(f_name)
                py_type = _resolve_type(f_type)

                if is_required:
                    # 必填字段
                    if py_type in ("list", "List[Any]"):
                        lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=list)")
                    elif py_type in ("dict", "Dict[str, Any]"):
                        lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=dict)")
                    else:
                        lines.append(f"    {cleaned_name}: {py_type}")
                elif default_val is not None:
                    # 有默认值
                    default_str = _format_default_value(default_val, f_type)
                    if py_type in ("list", "List[Any]") and default_val is None:
                        lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=list)")
                    elif py_type in ("dict", "Dict[str, Any]") and default_val is None:
                        lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=dict)")
                    else:
                        lines.append(f"    {cleaned_name}: {py_type} = {default_str}")
                else:
                    # 非必填无默认值
                    lines.append(f"    {cleaned_name}: {py_type} = None")
        else:
            lines.append("    pass")
        lines.append("")
        lines.append("")

    # 在文件头部插入所有嵌套模型（在第一个 class 之前）
    if all_nested_models:
        nested_lines = ["\n# ── 内嵌对象模型 ────────────────────────────────────\n"]
        for n_name, n_fields in all_nested_models.items():
            nested_lines.append(f"class {n_name}(BaseModel):")
            nested_lines.append(f'    """{_sanitize_name(n_name)}"""')
            if n_fields:
                for nf_name, nf_type, nf_required, nf_default in n_fields:
                    cleaned_name = _sanitize_name(nf_name)
                    py_type = _resolve_type(nf_type)
                    if nf_required:
                        if "List" in py_type or py_type == "list":
                            nested_lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=list)")
                        elif "Dict" in py_type or py_type == "dict":
                            nested_lines.append(f"    {cleaned_name}: {py_type} = Field(default_factory=dict)")
                        else:
                            nested_lines.append(f"    {cleaned_name}: {py_type}")
                    elif nf_default is not None:
                        default_str = _format_default_value(nf_default, nf_type)
                        nested_lines.append(f"    {cleaned_name}: {py_type} = {default_str}")
                    else:
                        nested_lines.append(f"    {cleaned_name}: {py_type} = None")
            else:
                nested_lines.append("    pass")
            nested_lines.append("")

        # 找到第一个类定义的位置
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith("class ") and "Input" not in line and "Output" not in line:
                # 跳过 Input 和 Output class，只找第一个自定义模型
                pass
            if line.startswith("class ") and insert_idx is None:
                insert_idx = i
                break
        if insert_idx is None:
            insert_idx = len(lines)

        # 在第一个模型之前插入嵌套模型
        for nl in reversed(nested_lines):
            lines.insert(insert_idx, nl)

    return "\n".join(lines)


def _extract_input_fields(params: Any) -> List[tuple]:
    """从 params 提取输入字段

    支持：
    - 旧格式（字符串列表）: ["a: float", "b: float"]
    - 新格式（已解析的 dict 列表）: [{"name": "a", "raw_type": "float", "py_type": "float"}]
    """
    fields = []
    if not params:
        return fields

    for param in params:
        if isinstance(param, str):
            # 旧格式: "a: float"
            parts = param.split(":")
            p_name = parts[0].strip()
            p_type = parts[1].strip() if len(parts) > 1 else "str"
            fields.append((p_name, p_type, None))
        elif isinstance(param, dict):
            # 新格式: {"name": "a", "raw_type": "float", ...}
            p_name = param.get("name", "unknown")
            p_type = param.get("raw_type", "str")
            p_default = param.get("default")
            fields.append((p_name, p_type, p_default))

    return fields


def _extract_field_from_normalized(normalized_fields: Dict[str, Any]) -> List[tuple]:
    """从归一化的嵌套字段字典提取字段列表

    输入: {"user_id": {"type": "str", "required": true, "default": None, ...}, ...}
    输出: [("user_id", "str", True, None), ...]
    """
    fields = []
    for f_name, f_def in normalized_fields.items():
        if isinstance(f_def, dict):
            f_type = get_field_def_type(f_def)
            f_required = get_field_def_required(f_def)
            f_default = get_field_def_default(f_def)
            fields.append((f_name, f_type, f_required, f_default))
        else:
            fields.append((f_name, "any", False, f_def))
    return fields


# ── 磁盘写入函数 ─────────────────────────────────────────────────


def write_models_to_disk(
    worker_dir: str,
    dry_run: bool = False,
    target_path: Optional[str] = None,
    shared_only: bool = False,
) -> str:
    """
    为指定 worker 生成 Pydantic 模型并写入 models/__init__.py

    :param worker_dir: worker 目录路径
    :param dry_run: 如果为 True，只返回代码而不写入文件
    :param target_path: 自定义输出文件路径（如 public/__init__.py），
                        传入后将直接写入该路径而非 models/__init__.py
    :param shared_only: 如果为 True，只生成标记为 shared = true 的 handler 模型
    :return: 生成的代码字符串
    """
    code = generate_models(worker_dir, shared_only=shared_only)

    if dry_run:
        return code

    if target_path:
        target_path = os.path.abspath(target_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code)
    else:
        models_dir = os.path.join(worker_dir, "models")
        os.makedirs(models_dir, exist_ok=True)
        init_file = os.path.join(models_dir, "__init__.py")
        with open(init_file, "w", encoding="utf-8") as f:
            f.write(code)

    return code


def get_worker_names() -> List[str]:
    """获取所有可用的 worker 名称列表"""
    project_root = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", ".."
    )
    workers_dir = os.path.join(project_root, "workers")
    if not os.path.exists(workers_dir):
        return []
    return [
        d
        for d in os.listdir(workers_dir)
        if os.path.isdir(os.path.join(workers_dir, d))
        and os.path.exists(os.path.join(workers_dir, d, "config.toml"))
    ]
