# Utils JWT — chongming-jwt

**Package:** `chongming_jwt`  
**Location:** `utils/python/jwt/src/chongming_jwt/`  
**Entry Point:** `chongming_jwt.JWTAuth`

JWT 认证工具库，为 chongming gateway 提供 token 的 **创建**、**解码验证** 与 **用户信息提取** 能力。支持 HMAC、RSA、ECDSA、EdDSA 签名算法，以及 JWKS 动态密钥解析。

---

## 类：`JWTAuth`

### 构造函数

```python
class JWTAuth(config: Dict[str, Any])
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `dict` | 见下方「配置项」表格 |

**配置项：**

| Key | 类型 | 默认值 | 必填 | 说明 |
|-----|------|--------|------|------|
| `enabled` | `bool` | `False` | 否 | 启用 JWT 功能 |
| `algorithm` | `str` | `"HS256"` | 否 | 签名算法：`HS256` `HS384` `HS512` `RS256` `RS384` `RS512` `ES256` `ES384` `ES512` `EdDSA` |
| `secret_key` | `str` | — | HMAC 必填 | HMAC 对称密钥 |
| `private_key_path` | `str` | — | 非对称算法必填 | 私钥文件路径（PEM 格式） |
| `public_key_path` | `str` | — | 非对称验证时必填 | 公钥文件路径（PEM 格式） |
| `jwks_url` | `str` | — | 否 | JWKS 端点 URL，用于动态获取签名公钥 |
| `issuer` | `str` | — | 否 | 预期的 `iss` 声明。设置后在创建和验证时均会使用 |
| `audience` | `str` | — | 否 | 预期的 `aud` 声明。设置后在创建和验证时均会使用 |
| `user_id_claim` | `str` | `"sub"` | 否 | `get_user_info()` 提取 user_id 的字段名 |
| `roles_claim` | `str` | `"roles"` | 否 | `get_user_info()` 提取 roles 的字段名 |
| `whitelist_paths` | `list[str]` | `[]` | 否 | 跳过 JWT 认证的路径前缀列表 |
| `token_expire_seconds` | `int` | `3600` | 否 | `create_token()` 默认过期时间（秒） |

**算法与所需配置对照：**

| 算法 | 类型 | 对称/非对称 | 创建 token 所需 | 验证 token 所需 |
|------|------|------------|----------------|----------------|
| HS256 / HS384 / HS512 | HMAC | 对称 | `secret_key` | `secret_key` |
| RS256 / RS384 / RS512 | RSA | 非对称 | `private_key_path` | `public_key_path` 或 `jwks_url` |
| ES256 / ES384 / ES512 | ECDSA | 非对称 | `private_key_path` | `public_key_path` 或 `jwks_url` |
| EdDSA | Ed25519 | 非对称 | `private_key_path` | `public_key_path` 或 `jwks_url` |

**示例：**

```python
from chongming_jwt import JWTAuth

# HMAC 对称密钥
auth = JWTAuth({
    "enabled": True,
    "algorithm": "HS256",
    "secret_key": "your-256-bit-secret-key",
    "issuer": "chongming",
    "audience": "chongming-api",
})

# RSA 非对称密钥
auth = JWTAuth({
    "enabled": True,
    "algorithm": "RS256",
    "private_key_path": "/path/to/private.pem",
    "public_key_path": "/path/to/public.pem",
    "issuer": "chongming",
})

# JWKS 动态密钥
auth = JWTAuth({
    "enabled": True,
    "algorithm": "RS256",
    "jwks_url": "https://auth.example.com/.well-known/jwks.json",
    "issuer": "chongming",
    "audience": "chongming-api",
})
```

---

### `create_token(payload, expires_in=None, issuer=None, audience=None, subject=None)`

创建并签名 JWT token。

```python
def create_token(
    self,
    payload: Dict[str, Any],
    expires_in: Optional[int] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    subject: Optional[str] = None,
) -> Optional[str]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `payload` | `dict` | — | **必填**。自定义声明，如 `{"user_id": "123", "roles": ["admin"]}` |
| `expires_in` | `int` 或 `None` | 取自配置 `token_expire_seconds`（默认 `3600`） | Token 过期秒数。传 `0` 或 `None` 表示不设置过期时间 |
| `issuer` | `str` 或 `None` | 取自配置 `issuer` | 覆盖 `iss` 声明。传空字符串表示不设置 |
| `audience` | `str` 或 `None` | 取自配置 `audience` | 覆盖 `aud` 声明。传空字符串表示不设置 |
| `subject` | `str` 或 `None` | 自动推导（见下方说明） | 显式设置 `sub` 声明，优先级最高 |

**`sub` 声明自动推导逻辑（按优先级）：**

1. `subject` 参数（显式传入）
2. `payload` 中的 `"sub"` 键
3. `payload` 中 `user_id_claim` 配置项对应的键（如果 `user_id_claim != "sub"`）
4. `payload` 中的 `"user_id"` 键（兜底）

**返回：**

- 成功 → 编码后的 JWT token 字符串（`str`）
- 失败（JWT 未启用或缺少签名密钥）→ `None`

**异常：**

- `jwt.PyJWTError` — 签名失败时抛出

**自动注入的标准声明：**

| 声明 | 来源 | 说明 |
|------|------|------|
| `iss` | `issuer` 参数 / 配置 `issuer` | 签发者 |
| `aud` | `audience` 参数 / 配置 `audience` | 目标受众 |
| `sub` | 自动推导逻辑 | 主题（用户标识） |
| `iat` | 自动 | 签发时间（Unix 时间戳） |
| `exp` | `expires_in` 参数 / 配置 `token_expire_seconds` | 过期时间（Unix 时间戳，仅在过期秒数 > 0 时设置） |

**示例：**

```python
# 基础用法
token = auth.create_token({
    "user_id": "u_abc123",
    "roles": ["admin"],
    "username": "alice",
})

# 自定义过期时间（5 分钟）
token = auth.create_token(
    {"user_id": "u_abc123", "roles": ["user"]},
    expires_in=300,
)

# 显式覆盖所有标准声明
token = auth.create_token(
    {"user_id": "u_abc123", "roles": ["admin"]},
    expires_in=7200,
    issuer="custom-issuer",
    audience="custom-audience",
    subject="explicit-subject",
)
```

**生成的 JWT payload 示例：**

```json
{
  "iss": "chongming",
  "aud": "chongming-api",
  "sub": "u_abc123",
  "iat": 1780128000,
  "exp": 1780131600,
  "user_id": "u_abc123",
  "roles": ["admin"],
  "username": "alice"
}
```

---

### `decode_token(token)`

解码并验证 JWT token。根据配置的算法自动选择验证方式（HMAC 对称验证、公钥验证、或 JWKS 动态密钥验证）。

```python
def decode_token(self, token: str) -> Optional[Dict[str, Any]]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `token` | `str` | **必填**。待解码的 JWT token 字符串 |

**自动验证的声明：**

| 声明 | 验证内容 | 配置来源 |
|------|---------|---------|
| `iss` | 精确匹配 | 配置 `issuer`（仅在配置该项时验证） |
| `aud` | 精确匹配 | 配置 `audience`（仅在配置该项时验证） |
| `exp` | 未过期 | 自动 |
| `iat` | 有效性检查 | 自动 |
| 签名 | 算法匹配 + 密钥验证 | 配置 `algorithm` + `secret_key` / `public_key` / JWKS |

**验证策略自动选择：**

| 场景 | 验证方式 |
|------|---------|
| HMAC 算法（`HS*`） | 使用 `secret_key` 进行对称验证 |
| 配置了 `jwks_url` | 从 JWKS 端点获取签名密钥进行验证 |
| 其他（`RS*`/`ES*`/`EdDSA`） | 使用 `public_key` 进行非对称验证 |

**返回：**

- 成功 → 解码后的 payload（`dict`），包含所有注册声明和自定义声明
- 失败 → `None`（token 过期、签名无效、发行者/受众不匹配等）

**可能静默处理的异常：**

| 异常类型 | 触发条件 |
|---------|---------|
| `jwt.ExpiredSignatureError` | Token 已过期（`exp` 声明早于当前时间） |
| `jwt.InvalidTokenError` | 签名无效、`iss`/`aud` 不匹配、格式错误等 |

**示例：**

```python
payload = auth.decode_token(token)
if payload:
    print(f"Token is valid for user: {payload.get('sub')}")
else:
    print("Token is invalid or expired")
```

---

### `get_user_info(payload)`

从已解码的 JWT payload 中提取 **用户标识** 和 **角色列表**。

```python
def get_user_info(self, payload: Dict[str, Any]) -> Dict[str, Any]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `payload` | `dict` | **必填**。`decode_token()` 返回的 payload |

**提取逻辑：**

| 返回字段 | 来源 | 配置项 | 默认值 |
|---------|------|--------|--------|
| `user_id` | `payload[self.user_id_claim]` | `user_id_claim` | `"sub"` |
| `roles` | `payload[self.roles_claim]` | `roles_claim` | `"roles"` |

**注意：**
- 如果 `roles` 不是列表类型，会尝试包装为单元素列表；若为空则返回空列表 `[]`
- `user_id` 始终转换为字符串类型

**返回：**

```python
{"user_id": str, "roles": list}
```

**示例：**

```python
payload = auth.decode_token(token)
# payload = {
#   "sub": "u_abc123",
#   "roles": ["admin", "editor"],
#   "username": "alice",
#   ...
# }

user_info = auth.get_user_info(payload)
# {'user_id': 'u_abc123', 'roles': ['admin', 'editor']}
```

**自定义字段提取：**

```python
auth = JWTAuth({
    "enabled": True,
    "secret_key": "mykey",
    "user_id_claim": "uid",
    "roles_claim": "permissions",
})

payload = auth.decode_token(token)
# payload = {"uid": "123", "permissions": ["read", "write"]}

user_info = auth.get_user_info(payload)
# {'user_id': '123', 'roles': ['read', 'write']}
```

---

### `is_whitelisted(path)`

检查指定路径是否在认证白名单中。白名单中的路径不需要 JWT 认证即可访问。

```python
def is_whitelisted(self, path: str) -> bool
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `path` | `str` | **必填**。请求路径字符串 |

**匹配逻辑：**
- 遍历 `whitelist_paths` 配置列表
- 如果 `path` 以任一白名单路径前缀开头，返回 `True`
- 如果 JWT 未启用（`enabled=False`），始终返回 `True`

**返回：** `bool`

**示例：**

```python
auth = JWTAuth({
    "enabled": True,
    "secret_key": "mykey",
    "whitelist_paths": ["/health", "/public"],
})

auth.is_whitelisted("/health")      # True
auth.is_whitelisted("/public/login")  # True
auth.is_whitelisted("/api/data")    # False
```

---

## 完整使用流程

### Token 创建端（客户端 / 测试脚本）

```python
from chongming_jwt import JWTAuth
import requests

# 1. 初始化（配置必须与 Gateway 一致）
auth = JWTAuth({
    "enabled": True,
    "algorithm": "HS256",
    "secret_key": "your-256-bit-secret-key",
    "issuer": "chongming",
    "audience": "chongming-api",
})

# 2. 创建 token
token = auth.create_token({
    "user_id": "u_admin",
    "roles": ["admin"],
    "username": "admin",
})

# 3. 携带 token 调用 API
resp = requests.get(
    "http://localhost:8000/calc/add?a=3&b=4",
    headers={"Authorization": f"Bearer {token}"},
)
```

### Token 验证端（Gateway 内部）

```python
from chongming_jwt import JWTAuth

auth = JWTAuth(gateway_jwt_config)

def on_request(request):
    # 1. 检查白名单
    if auth.is_whitelisted(request.path):
        return forward_to_worker(request)

    # 2. 提取 token
    token = extract_bearer_token(request.headers)

    # 3. 验证 token
    payload = auth.decode_token(token)
    if not payload:
        return respond_401("Invalid or expired token")

    # 4. 提取用户信息
    user_info = auth.get_user_info(payload)
    request.user = user_info

    return forward_to_worker(request)
```

---

## 架构集成

```
┌──────────────┐     Authorization: Bearer <token>     ┌──────────────────┐
│  客户端/测试  │ ──────────────────────────────────▶  │    Gateway        │
│  (create_token) │                                    │  (decode_token)    │
└──────────────┘                                       │  (is_whitelisted)  │
                                                        │  (get_user_info)   │
                                                        └────────┬─────────┘
                                                                 │ user_info 注入请求
                                                                 ▼
                                                        ┌──────────────────┐
                                                        │     Worker        │
                                                        │  (auth_required   │
                                                        │   = true 的路由)   │
                                                        └──────────────────┘
