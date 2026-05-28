import logging
import uuid
from .nats_client import get_nats_client
from fastapi import Request, HTTPException, FastAPI
import json
import asyncio
from typing import List, Optional, Dict, Any, Type, Union, Tuple
import re
from pydantic import BaseModel, create_model
from chongming_lock import MutexLock, LockNotAcquiredError
from chongming_logging import set_request_id, get_request_id

logger = logging.getLogger("chongming.gateway.dynamic_route")

# 类型名称到 Python 类型的映射表（用于 JSON 序列化/反序列化场景）
_TYPE_MAP: Dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "any": Any, # type: ignore
}

# 支持校验的参数类型列表
_VALID_TYPES = {"str", "int", "float", "bool"}


class DynamicRoute:
    """动态路由管理器——采用 app.state 单例模式。
    
    使用方式（由 lifespan 创建一次并存放在 app.state）:
        app.state.dynamic_route_manager = DynamicRoute(app)
    
    功能:
    - 动态添加/移除 FastAPI 路由
    - 通过 NATS 请求转发至 worker
    - 响应模型动态创建
    - 路由生命周期管理

    设计说明:
    所有动态路由直接注册到 app.router（FastAPI 根路由），不使用 APIRouter 实例分组。
    'router_prefix' 参数仅用于路径前缀管理和 OpenAPI tags，不创建独立的路由器。
    路由信息（前缀、路径、方法等）均从 app.routes 实时提取。
    """

    def __init__(self, app: FastAPI):
        self.app = app
        self._route_lock = asyncio.Lock()

    # ──────────────────────────────────────────────
    # 类型系统
    # ──────────────────────────────────────────────

    def _resolve_type(self, type_spec: Any) -> type:
        """将类型定义解析为 Python 类型对象。
        
        支持:
        - 字符串类型名: "str", "int", "float", "bool", "dict", "list", "any"
        - Python 类型对象: str, int, float (用于直接代码调用)
        - 其他值原样返回
        """
        if isinstance(type_spec, str):
            resolved = _TYPE_MAP.get(type_spec.lower())
            if resolved is None:
                raise ValueError(
                    f"Unknown type name '{type_spec}'. Supported types: {list(_TYPE_MAP.keys())}"
                )
            return resolved
        if isinstance(type_spec, type):
            return type_spec
        return type_spec

    def _get_type_name(self, t: type) -> str:
        """获取类型名称字符串（反向映射）"""
        for name, typ in _TYPE_MAP.items():
            if typ == t:
                return name
        return str(t.__name__)

    def _model_name_from_subject(self, subject: str) -> str:
        """从 subject 生成合法的 Python 类名。"""
        parts = subject.replace("-", "_").split(".")
        class_name = "".join(part.capitalize() for part in parts if part)
        if not class_name:
            class_name = "Response"
        return class_name

    def _create_response_model(
        self,
        model_def: Union[Dict[str, Any], Type[BaseModel], List[str], None],
        subject: str = "",
    ) -> Optional[Type[BaseModel]]:
        """动态创建 Pydantic response_model。"""
        if model_def is None:
            return None

        if isinstance(model_def, type) and issubclass(model_def, BaseModel):
            return model_def

        model_name_prefix = self._model_name_from_subject(subject)
        model_name = f"{model_name_prefix}Response"

        if isinstance(model_def, dict):
            normalized_fields = {}
            for field_name, field_type in model_def.items():
                if isinstance(field_type, (tuple, list)):
                    type_spec, default = field_type[0], field_type[1]
                    resolved_type = self._resolve_type(type_spec)
                    if isinstance(default, str) and default == "__required__":
                        normalized_fields[field_name] = (resolved_type, ...)
                    else:
                        normalized_fields[field_name] = (resolved_type, default)
                elif isinstance(field_type, type):
                    normalized_fields[field_name] = (field_type, None)
                elif isinstance(field_type, str):
                    resolved_type = self._resolve_type(field_type)
                    normalized_fields[field_name] = (resolved_type, None)
                else:
                    raise ValueError(
                        f"Unsupported field definition for '{field_name}': {field_type}. "
                        f"Expected (type, default) tuple, a type class, or a type name string."
                    )
            return create_model(model_name, **normalized_fields)

        if isinstance(model_def, list):
            fields = {name: (str, ...) for name in model_def}
            return create_model(model_name, **fields) # type: ignore

        raise ValueError(
            f"Unsupported response_model type: {type(model_def)}. "
            f"Expected None, a BaseModel subclass, a dict, or a list of field names."
        )

    # ──────────────────────────────────────────────
    # 参数解析（从 "name: type" 格式）
    # ──────────────────────────────────────────────

    @staticmethod
    def _parse_params(params: List[str]) -> Tuple[List[str], Dict[str, str]]:
        """解析 "name: type" 格式的参数列表。
        
        返回:
        - param_names: 纯参数名列表 ["a", "b"]
        - param_types: 参数名到类型的映射 {"a": "float", "b": "float"}
        """
        param_names = []
        param_types = {}

        for p in params:
            p = p.strip()
            if not p:
                continue

            if ":" in p:
                # "name: type" 格式
                parts = p.rsplit(":", 1)
                name = parts[0].strip()
                type_str = parts[1].strip().lower() if len(parts) > 1 else "str"
            else:
                # 只有参数名，无类型声明 → 默认为 str
                name = p
                type_str = "str"

            # 校验类型是否合法
            if type_str not in _VALID_TYPES:
                logger.warning(
                    "Unknown param type '%s' for '%s', defaulting to 'str'",
                    type_str, name
                )
                type_str = "str"

            param_names.append(name)
            param_types[name] = type_str

        return param_names, param_types

    # ──────────────────────────────────────────────
    # 参数类型校验（严格模式）
    # ──────────────────────────────────────────────

    @staticmethod
    def _validate_and_cast(value: str, target_type: str, param_name: str) -> Any:
        """严格校验并转换参数值。
        
        如果类型不匹配，抛出 ValueError 并说明原因。
        
        返回转换后的值，或抛出异常。
        """
        if target_type in ("str", "any"):
            return value

        try:
            if target_type == "int":
                # 严格校验：必须是纯整数，浮点数字符串如 "10.5" 不接受
                if not re.match(r'^-?\d+$', value.strip()):
                    raise ValueError(f"invalid integer value: '{value}'")
                return int(value)

            elif target_type == "float":
                # 严格校验浮点数
                try:
                    return float(value)
                except ValueError:
                    raise ValueError(f"invalid float value: '{value}'")

            elif target_type == "bool":
                if isinstance(value, str):
                    lower_val = value.lower().strip()
                    if lower_val in ('true', '1', 'yes'):
                        return True
                    elif lower_val in ('false', '0', 'no'):
                        return False
                    else:
                        raise ValueError(
                            f"invalid bool value: '{value}'. "
                            f"Expected true/false, 1/0, yes/no"
                        )
                return bool(value)

        except ValueError:
            raise

        return value

    # ──────────────────────────────────────────────
    # OpenAPI schema 刷新
    # ──────────────────────────────────────────────

    def refresh_openapi(self):
        """刷新 OpenAPI schema 缓存"""
        self.app.openapi_schema = None

    # ──────────────────────────────────────────────
    # 增删路由（公开接口）
    # ──────────────────────────────────────────────

    async def add_dynamic_route(
        self,
        subject: str,
        method: str,
        path: str,
        params: List[str],
        summary: Optional[str] = None,
        docstring: Optional[str] = None,
        router_prefix: Optional[str] = None,
        tags: Optional[List[str]] = None,
        timeout: float = 2.0,
        response_model: Optional[Union[Dict[str, Any], Type[BaseModel], List[str]]] = None,
    ):
        """添加动态路由。
        
        所有路由直接注册到 app.router，确保即时生效。
        'router_prefix' 用于:
        - 构造完整路径（prefix + relative_path）
        - 派生默认 tags
        - 路由冲突检测时作为路径的一部分

        'params' 支持两种格式:
        - 纯参数名: ["a", "b"] → 类型默认为 str
        - 带类型声明: ["a: float", "b: float"] → 网关层做严格类型校验
        
        支持的参数类型: str, int, float, bool
        类型校验失败时返回 HTTP 400 错误，不会转发给 Worker。
        """
        # ── 解析参数类型声明 ──────────────────────────────
        param_names, param_types = self._parse_params(params)

        if not router_prefix:
            parts = path.split('/')
            if len(parts) > 1 and parts[1]:
                router_prefix = f"/{parts[1]}"
            else:
                router_prefix = "/default"

        # 计算相对路径：path 中去除 router_prefix 的部分
        if path.startswith(router_prefix):
            relative_path = path[len(router_prefix):] or "/"
        else:
            relative_path = path
        if not relative_path.startswith("/"):
            relative_path = "/" + relative_path

        if not tags:
            tags = [router_prefix.strip('/') or "default"]

        if docstring is None:
            docstring = f"Handler for {subject}"

        if summary is None:
            summary = f"Call {subject}"

        resolved_response_model = self._create_response_model(response_model, subject=subject)

        async def handler(request: Request):
            # ── 生成分布式追踪 ID ─────────────────────────────────
            request_id = str(uuid.uuid4())
            set_request_id(request_id)

            data = dict(request.query_params)
            if request.method in ("POST", "PUT"):
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        data.update(body)
                except:
                    pass

            # ── 参数类型校验与转换（严格模式） ─────────────────
            # 根据 params 中声明的类型（"a: float"）进行严格校验
            # 类型不匹配时直接返回 400 Bad Request，不转发给 Worker
            converted = {}
            for p in param_names:
                raw_value = data.get(p)
                if raw_value is None:
                    converted[p] = None
                    continue

                target_type = param_types.get(p, "str")
                try:
                    converted[p] = self._validate_and_cast(raw_value, target_type, p)
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Parameter '{p}': {e}"
                    )

            payload = json.dumps(converted).encode()

            try:
                nc = await get_nats_client()
                resp = await nc.request(
                    subject, payload,
                    timeout=timeout,
                    headers={"request_id": request_id},
                )
                worker_request_id = resp.headers.get("request_id", "") if resp.headers else ""
                if worker_request_id and worker_request_id != request_id:
                    logger.warning(
                        "request_id mismatch: gateway=%s worker=%s",
                        request_id, worker_request_id,
                    )
                try:
                    result = json.loads(resp.data.decode())
                except:
                    result = resp.data.decode()
                if resolved_response_model is not None:
                    return result
                return {"result": result}
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Service timeout")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # 构建 OpenAPI 参数描述
        path_params_set = set(re.findall(r'\{(\w+)\}', relative_path))
        openapi_params = []
        for p in param_names:
            param_in = "path" if p in path_params_set else "query"

            # 在 OpenAPI schema 中标注参数类型
            type_name = param_types.get(p, "str")
            openapi_type_map = {
                "int": "integer",
                "float": "number",
                "bool": "boolean",
                "str": "string",
            }
            openapi_type = openapi_type_map.get(type_name, "string")
            param_schema = {"type": openapi_type}

            openapi_params.append({
                "name": p,
                "in": param_in,
                "required": param_in == "path",
                "schema": param_schema,
                "description": f"Parameter '{p}' (type: {type_name}) for {subject}",
            })
        openapi_extra = {"parameters": openapi_params}

        async with self._route_lock:
            # 构造完整路径
            full_path = router_prefix.rstrip('/') + '/' + relative_path.lstrip('/')
            method_set = {method.upper()}

            # 从 app.routes 中移除已存在的同名路由（确保幂等性）
            existing = [
                r for r in self.app.routes
                if getattr(r, "path", "") == full_path and getattr(r, "methods", set()) == method_set
            ]
            for r in existing:
                self.app.routes.remove(r)
                logger.info("Removed existing route from app: %s %s", method, full_path)

            # 构建路由关键字参数
            route_kwargs = dict(
                methods=[method],
                summary=summary,
                tags=tags,
                description=docstring,
                openapi_extra=openapi_extra,
            )
            if resolved_response_model is not None:
                route_kwargs["response_model"] = resolved_response_model # type: ignore

            # 直接注册到 FastAPI 根路由
            self.app.router.add_api_route(full_path, handler, **route_kwargs) # type: ignore
            self.refresh_openapi()

        # 打印注册信息
        response_model_info = ""
        if resolved_response_model is not None:
            model_name = resolved_response_model.__name__
            model_types = {
                name: self._get_type_name(field.annotation) # type: ignore
                for name, field in resolved_response_model.model_fields.items()
            }
            response_model_info = f", response_model: {model_name}{model_types}"
        logger.info(
            "Route added: %s %s -> NATS %s [params=%s]%s",
            method, full_path, subject, param_types, response_model_info
        )

    async def remove_dynamic_route(self, router_prefix: str, path: str, method: str):
        """从 app.routes 中移除指定路由"""
        # 计算完整路径（app.routes 中存储的是完整路径）
        if path.startswith(router_prefix):
            relative_path = path[len(router_prefix):] or "/"
        else:
            relative_path = path
        if not relative_path.startswith("/"):
            relative_path = "/" + relative_path
        full_path = router_prefix.rstrip('/') + '/' + relative_path.lstrip('/')

        async with self._route_lock:
            method_set = {method.upper()}

            # 从 app.routes 中移除
            removed = [
                r for r in self.app.routes
                if getattr(r, "path", "") == full_path and getattr(r, "methods", set()) == method_set
            ]
            for r in removed:
                self.app.routes.remove(r)
                logger.info("Removed route from app: %s %s", method, full_path)

            self.refresh_openapi()

            if not removed:
                logger.warning("No route found for %s %s", method, full_path)

    def get_registered_prefixes(self) -> List[str]:
        """从 app.routes 中提取唯一的 router prefix 列表（用于调试）"""
        prefixes: set = set()
        for route in self.app.routes:
            path = getattr(route, "path", None)
            if path is None:
                continue
            # 提取第一个路径段作为 prefix
            parts = path.strip("/").split("/")
            if parts and parts[0]:
                prefixes.add(f"/{parts[0]}")
        return sorted(prefixes)

    def get_registered_routes(self) -> List[Dict[str, Any]]:
        """从 app.routes 提取路由详情（用于调试）"""
        routes = []
        for route in self.app.routes:
            path = getattr(route, "path", None)
            if path is None:
                continue
            # 提取 prefix（第一个路径段）
            parts = path.strip("/").split("/")
            prefix = f"/{parts[0]}" if parts and parts[0] else "/"
            routes.append({
                "prefix": prefix,
                "path": path,
                "methods": sorted(getattr(route, "methods", set())),
                "name": getattr(route, "name", ""),
            })
        return routes
