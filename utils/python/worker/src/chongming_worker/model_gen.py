"""
Pydantic Model Generator
=========================

从 config.toml 中定义的 handler 元数据，自动生成对应的 Pydantic 输入/输出模型类。

使用方法::

    # 在 worker 根目录执行
    chongming gen-models example

    # 或在代码中直接调用
    from chongming_worker.model_gen import generate_models
    generate_models("workers/example")

模块会读取 config.toml 中 registration.items 的配置，
为每个 subject 生成 {Subject}Input 和 {Subject}Output 两个 Pydantic 模型类，
存放于 models/__init__.py 文件中。
"""

import ast
import os
import re
from typing import Any, Optional

from chongming_config import load_config

# ── 类型映射表 ─────────────────────────────────────────────────────
# config.toml 中的类型名 → Python/Pydantic 类型
_TYPE_MAP: dict[str, str] = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "object": "dict",
    "any": "Any",
}

# Python 关键字/内置类型保留字，需要加后缀避免冲突
_PYTHON_RESERVED = {
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
    "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "True", "False", "None", "type", "list", "dict", "str", "int",
    "float", "bool", "object", "input", "output", "model",
}


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
    # 先按分隔符拆分
    parts = re.split(r'[-_.\s]', name)
    return ''.join(part.capitalize() for part in parts if part)


def _toml_type_to_python(toml_type: str) -> str:
    """config.toml 中的类型描述 → Python 类型注解字符串"""
    toml_type = toml_type.strip().lower()
    # 处理 Optional[type]: 如果类型以 ? 结尾
    is_optional = toml_type.endswith("?")
    if is_optional:
        toml_type = toml_type.rstrip("?").strip()

    py_type = _TYPE_MAP.get(toml_type, toml_type)

    if is_optional:
        return f"Optional[{py_type}]"
    return py_type


def _parse_field(def_tuple: list) -> tuple[str, str, Any, Optional[dict]]:
    """解析 config.toml 中的一个字段定义

    字段定义格式::
        field_name = ["type", "default_or___required__"]
        field_name = ["type", "default_or___required__", {nested_fields}]

    :return: (field_name, type_annotation, default_value, nested_dict_or_None)
    """
    field_name = def_tuple[0]
    toml_type = def_tuple[1]
    default_raw = def_tuple[2] if len(def_tuple) > 2 else "__required__"
    nested = def_tuple[3] if len(def_tuple) > 3 else None

    return field_name, toml_type, default_raw, nested


def _generate_model_code(
    model_name: str,
    fields: list,
    is_input: bool = False,
    indent: int = 4,
) -> str:
    """生成单个 Pydantic 模型的源代码

    :param model_name: 类名（PascalCase）
    :param fields: 字段定义列表，每项为 [name, type, default, nested?]
    :param is_input: 是否为输入模型（输入模型直接使用 params 列表，没有默认值）
    :param indent: 缩进空格数
    :return: Python 源代码字符串
    """
    lines: list[str] = []
    i_str = " " * indent

    lines.append(f"class {model_name}(BaseModel):")
    lines.append(f"{i_str}\"\"\"{model_name} - 自动生成{'输入' if is_input else '输出'}模型\"\"\"")

    if not fields:
        lines.append(f"{i_str}pass")
        lines.append("")
        return "\n".join(lines)

    for field_def in fields:
        if is_input:
            # 输入模型：直接使用类型，无默认值
            field_name, toml_type = field_def[0], field_def[1]
            py_type = _toml_type_to_python(toml_type)
            cleaned_name = _sanitize_name(field_name)
            lines.append(f"{i_str}{cleaned_name}: {py_type}")
        else:
            field_name, toml_type, default_raw, nested = _parse_field(field_def)
            cleaned_name = _sanitize_name(field_name)

            if isinstance(nested, dict):
                # 嵌套对象 → 生成子模型
                nested_name = _to_pascal_case(field_name)
                nested_fields = []
                for nest_key, nest_val in nested.items():
                    if isinstance(nest_val, list) and len(nest_val) >= 2:
                        nested_fields.append([nest_key, *nest_val])
                    else:
                        nested_fields.append([nest_key, "any", nest_val])

                lines.append(f"{i_str}{cleaned_name}: {nested_name}")
                lines.append("")
                # 递归生成嵌套模型（在当前行之前插入）
                nested_code = _generate_model_code(
                    nested_name, nested_fields, indent=indent
                )
                # 我们会在返回前处理嵌套模型的插入位置
                continue

            py_type = _toml_type_to_python(toml_type)

            if default_raw == "__required__":
                lines.append(f"{i_str}{cleaned_name}: {py_type}")
            else:
                # 处理默认值
                py_default = _format_default_value(default_raw, toml_type)
                lines.append(f"{i_str}{cleaned_name}: {py_type} = {py_default}")

    lines.append("")
    return "\n".join(lines)


def _format_default_value(raw: str, toml_type: str) -> str:
    """将 config.toml 中的默认值格式化为 Python 字面量"""
    toml_type = toml_type.strip().lower()

    if toml_type in ("str",):
        return repr(str(raw))
    elif toml_type in ("int",):
        try:
            return str(int(raw))
        except (ValueError, TypeError):
            return repr(str(raw))
    elif toml_type in ("float",):
        try:
            return str(float(raw))
        except (ValueError, TypeError):
            return repr(str(raw))
    elif toml_type in ("bool",):
        if isinstance(raw, str):
            return "True" if raw.lower() in ("true", "1", "yes") else "False"
        return str(bool(raw)).lower()
    elif toml_type in ("list",):
        return repr(raw) if isinstance(raw, list) else "[]"
    elif toml_type in ("object", "any"):
        return repr(raw) if isinstance(raw, dict) else "{}"
    else:
        return repr(str(raw))


def _generate_imports(has_nested: bool = False) -> str:
    """生成 import 部分"""
    imports = [
        "from datetime import datetime",
        "from typing import Any, Optional, List, Dict",
        "",
        "from pydantic import BaseModel, Field, field_validator",
        "",
    ]
    return "\n".join(imports)


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

    lines: list[str] = []
    has_nested = False

    # 文件头
    lines.append('"""')
    lines.append(f"Pydantic Models - 自动生成")
    lines.append(f"")
    lines.append(f"生成自: config.toml")
    lines.append(f"指令: chongming gen-models")
    lines.append('"""')
    lines.append("")

    # imports
    lines.append("from datetime import datetime")
    lines.append("from typing import Any, Optional, List, Dict")
    lines.append("")
    lines.append("from pydantic import BaseModel, Field")
    lines.append("")

    # 收集所有需要生成的模型
    all_nested_models: dict[str, list] = {}  # name -> fields

    for item in items:
        subject = item.get("subject", "")
        if not subject:
            continue

        subject_pascal = _to_pascal_case(subject)

        # ── 输入模型（基于 params） ────────────────────────
        params = item.get("params", [])
        input_fields = []
        for param in params:
            # params 格式: "a: float", "user_id: str"
            parts = param.split(":")
            p_name = parts[0].strip()
            p_type = parts[1].strip() if len(parts) > 1 else "str"
            input_fields.append([p_name, p_type])

        input_model_name = f"{subject_pascal}Input"
        lines.append(f"class {input_model_name}(BaseModel):")
        lines.append(f"    \"\"\"{subject.upper()} 请求参数模型\"\"\"")
        for field_def in input_fields:
            f_name, f_type = _sanitize_name(field_def[0]), _toml_type_to_python(field_def[1])
            lines.append(f"    {f_name}: {f_type}")
        lines.append("")
        lines.append("")

        # ── 输出模型（基于 response_model） ────────────────
        response_model = item.get("response_model", {})
        output_fields = []
        nested_models: dict[str, list] = {}

        for r_key, r_val in response_model.items():
            if isinstance(r_val, list) and len(r_val) >= 2:
                r_type = r_val[0]
                r_default = r_val[1] if len(r_val) > 1 else "__required__"
                r_nested = r_val[2] if len(r_val) > 2 else None

                if isinstance(r_nested, dict):
                    # 有嵌套对象
                    nested_name = _to_pascal_case(r_key)
                    nested_fields = []
                    for nk, nv in r_nested.items():
                        if isinstance(nv, list) and len(nv) >= 2:
                            nested_fields.append([nk, *nv])
                        else:
                            nested_fields.append([nk, "any", nv])
                    nested_models[nested_name] = nested_fields
                    output_fields.append([r_key, "object", "__required__", nested_name])
                    has_nested = True
                else:
                    output_fields.append([r_key, r_type, r_default])
            else:
                output_fields.append([r_key, "any", r_val])

        output_model_name = f"{subject_pascal}Output"

        # 先生成嵌套模型
        for nested_name, nested_fields in nested_models.items():
            all_nested_models[nested_name] = nested_fields

        # 生成输出模型
        lines.append(f"class {output_model_name}(BaseModel):")
        lines.append(f"    \"\"\"{subject.upper()} 响应结果模型\"\"\"")
        for field_def in output_fields:
            if len(field_def) == 4:
                # 嵌套对象
                f_name = _sanitize_name(field_def[0])
                f_type = field_def[3]
                f_default = field_def[2]
                if f_default == "__required__":
                    lines.append(f"    {f_name}: {f_type}")
                else:
                    lines.append(f"    {f_name}: {f_type} = {_format_default_value(f_default, 'object')}")
            elif len(field_def) >= 2:
                f_name = _sanitize_name(field_def[0])
                f_type = _toml_type_to_python(field_def[1])
                if len(field_def) >= 3 and field_def[2] != "__required__":
                    f_default = field_def[2]
                    py_default = _format_default_value(f_default, field_def[1])
                    lines.append(f"    {f_name}: {f_type} = {py_default}")
                else:
                    lines.append(f"    {f_name}: {f_type}")
        lines.append("")
        lines.append("")

    # 在 __init__.py 的开头插入所有嵌套模型
    if all_nested_models:
        # 找到第一个 class 定义的位置，在其之前插入嵌套模型
        nested_section = "\n# ── 内嵌对象模型 ────────────────────────────────────\n\n"
        for n_name, n_fields in all_nested_models.items():
            nested_section += f"class {n_name}(BaseModel):\n"
            nested_section += f'    """{n_name}"""\n'
            if not n_fields:
                nested_section += "    pass\n\n"
            else:
                for nf in n_fields:
                    nf_name = _sanitize_name(nf[0])
                    nf_type = _toml_type_to_python(nf[1] if len(nf) > 1 else "any")
                    nf_default = nf[2] if len(nf) > 2 else "__required__"
                    if nf_default == "__required__":
                        nested_section += f"    {nf_name}: {nf_type}\n"
                    else:
                        nested_section += f"    {nf_name}: {nf_type} = {_format_default_value(nf_default, nf[1] if len(nf) > 1 else 'any')}\n"
                nested_section += "\n"

        # 在文件头部插入嵌套模型（在第一个类之前）
        idx = 0
        for i, line in enumerate(lines):
            if line.startswith("class "):
                idx = i
                break
        # 插入在第一个 class 之前
        insert_lines = nested_section.strip().split("\n")
        for il in reversed(insert_lines):
            lines.insert(idx, il)
        lines.insert(idx, "")

    return "\n".join(lines)


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
        # 写入自定义路径（如 public/__init__.py）
        target_path = os.path.abspath(target_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code)
    else:
        # 默认写入 models/__init__.py
        models_dir = os.path.join(worker_dir, "models")
        os.makedirs(models_dir, exist_ok=True)
        init_file = os.path.join(models_dir, "__init__.py")
        with open(init_file, "w", encoding="utf-8") as f:
            f.write(code)

    return code


def get_worker_names() -> list[str]:
    """获取所有可用的 worker 名称列表"""
    project_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
    workers_dir = os.path.join(project_root, "workers")
    if not os.path.exists(workers_dir):
        return []
    return [
        d for d in os.listdir(workers_dir)
        if os.path.isdir(os.path.join(workers_dir, d))
        and os.path.exists(os.path.join(workers_dir, d, "config.toml"))
    ]
