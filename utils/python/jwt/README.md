# chongming-jwt

JWT 认证工具库，为 chongming gateway 提供 token 的 **创建** 与 **验证** 能力。

## 典型使用场景

在 chongming 架构中，JWT 认证的完整链路如下：

```
┌──────────────┐     Authorization: Bearer <token>     ┌──────────────┐
│  客户端/测试  │ ──────────────────────────────────▶   │   Gateway    │
│  (创建token)  │                                       │  (验证token)  │
└──────────────┘                                       └──────┬───────┘
                                                              │
                                                        转发至 Worker
                                                              │
                                                              ▼
                                                       ┌──────────────┐
                                                       │   Worker     │
                                                       │ (auth_required│
                                                       │  = true 的路由)│
                                                       └──────────────┘
```

### Worker 中的 `auth_required`

Worker 的 `config.toml` 中可对每个路由声明 `auth_required = true`，示例：

```toml
# workers/example/config.toml
[registration]
items = [
    {
        subject = "calc.add",
        method = "GET",
        path = "/add",
        auth_required = true,        # ← 此路由需要 JWT 认证
        params = ["a: float", "b: float"],
        # ...
    },
    {
        subject = "user.health_check",
        method = "GET",
        path = "/user/health",
        auth_required = false,       # ← 公开路由，无需认证
        # ...
    },
]
```

当 `auth_required = true` 时，Gateway 会要求请求头携带有效的 JWT token。此时你就需要 `chongming-jwt` 来创建 token。

## 快速开始

### 1. 安装

```bash
pip install chongming-jwt
```

### 2. 创建 Token（客户端/测试用）

```python
from chongming_jwt import JWTAuth

# 配置必须与 Gateway 的 config.toml 中的 [jwt] 段保持一致
config = {
    "enabled": True,
    "algorithm": "HS256",
    "secret_key": "your-256-bit-secret-key",
    "issuer": "chongming",
    "audience": "chongming-api",
    "token_expire_seconds": 3600,  # 可选，默认 1 小时
}
auth = JWTAuth(config)

# 创建 token（携带用户信息）
token = auth.create_token({
    "user_id": "123",
    "roles": ["admin"],
    "username": "alice",
})
# 输出类似: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# 在请求头中使用
# Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. 验证 Token（Gateway 内部使用）

```python
payload = auth.decode_token(token)
# {'iss': 'chongming', 'aud': 'chongming-api', 'iat': 1780128000,
#  'exp': 1780131600, 'user_id': '123', 'roles': ['admin']}

user_info = auth.get_user_info(payload)
# {'user_id': '123', 'roles': ['admin']}
```

## 完整示例

### Gateway 配置（`api_gateway/config.toml`）

```toml
[jwt]
enabled = true
algorithm = "HS256"
secret_key = "your-256-bit-secret-key"
issuer = "chongming"
audience = "chongming-api"
user_id_claim = "sub"
roles_claim = "roles"
token_expire_seconds = 3600
whitelist_paths = ["/health", "/public"]
```

### 测试 Worker 受保护路由

```python
from chongming_jwt import JWTAuth
import requests

# 1. 创建 token（与 Gateway 配置一致的 secret）
auth = JWTAuth({
    "enabled": True,
    "algorithm": "HS256",
    "secret_key": "your-256-bit-secret-key",
    "issuer": "chongming",
    "audience": "chongming-api",
})
token = auth.create_token({
    "user_id": "admin",
    "roles": ["admin"],
})

# 2. 调用受保护的路由
resp = requests.get(
    "http://localhost:8000/calc/add?a=3&b=4",
    headers={"Authorization": f"Bearer {token}"},
)
print(resp.json())
# {'result': 7.0, 'operation': 'add', 'timestamp': 1780128000.0}
```

## 配置项

| Key | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | bool | `False` | 启用 JWT |
| `algorithm` | str | `"HS256"` | 签名算法：`HS256` `HS384` `HS512` `RS256` `RS384` `RS512` `ES256` `ES384` `ES512` `EdDSA` |
| `secret_key` | str | — | HMAC 对称密钥（HS* 算法必填） |
| `private_key_path` | str | — | 私钥文件路径（RS/ES/Ed 算法必填） |
| `public_key_path` | str | — | 公钥文件路径（RS/ES/Ed 验证用） |
| `jwks_url` | str | — | JWKS 端点 URL（动态密钥解析） |
| `issuer` | str | — | 预期的 `iss` 声明 |
| `audience` | str | — | 预期的 `aud` 声明 |
| `user_id_claim` | str | `"sub"` | 提取 user_id 的字段名 |
| `roles_claim` | str | `"roles"` | 提取 roles 的字段名 |
| `whitelist_paths` | list | `[]` | 跳过认证的路径前缀 |
| `token_expire_seconds` | int | `3600` | token 默认过期时间（秒） |

## 支持的签名算法

| 算法 | 类型 | 对称/非对称 | 所需配置项 |
|------|------|------------|-----------|
| HS256 / HS384 / HS512 | HMAC | 对称 | `secret_key` |
| RS256 / RS384 / RS512 | RSA | 非对称 | `private_key_path` + `public_key_path` |
| ES256 / ES384 / ES512 | ECDSA | 非对称 | `private_key_path` + `public_key_path` |
| EdDSA | Ed25519 | 非对称 | `private_key_path` + `public_key_path` |

### RSA 非对称签名示例

```python
config = {
    "enabled": True,
    "algorithm": "RS256",
    "private_key_path": "/path/to/private.pem",  # 创建 token 用
    "public_key_path": "/path/to/public.pem",    # 验证 token 用
    "issuer": "chongming",
}
auth = JWTAuth(config)

token = auth.create_token({
    "user_id": "123",
    "roles": ["admin"],
})
```

## API 参考

### `create_token(payload, expires_in=None, issuer=None, audience=None, subject=None)`

创建并签名 JWT token。

- **`payload`** (dict) — 自定义声明，如 `{"user_id": "123", "roles": ["admin"]}`
- **`expires_in`** (int, 可选) — 过期秒数，覆盖 `token_expire_seconds` 配置。传 `0` 或 `None` 表示永不过期
- **`issuer`** (str, 可选) — 覆盖配置中的 `issuer`
- **`audience`** (str, 可选) — 覆盖配置中的 `audience`
- **`subject`** (str, 可选) — 设置 `sub` 声明，优先级最高

**自动映射逻辑**：`create_token` 会自动将 `payload` 中的 `user_id` 或 `user_id_claim` 对应的字段映射到标准 `sub` 声明，方便 `get_user_info` 提取。

### `decode_token(token)`

解码并验证 JWT token。返回 payload dict，无效时返回 `None`。

### `get_user_info(payload)`

从解码后的 payload 中提取 `user_id` 和 `roles`。

### `is_whitelisted(path)`

检查路径是否在认证白名单中。
