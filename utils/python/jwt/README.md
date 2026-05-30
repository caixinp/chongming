# chongming-jwt

JWT authentication utility for chongming gateway.

## Features

- Support for HMAC (HS256, HS384, HS512) and RSA (RS256, RS384, RS512) algorithms
- JWKS (JSON Web Key Set) support for dynamic key resolution
- Configurable issuer and audience validation
- User info extraction with customizable claims
- Path whitelist for bypassing authentication

## Usage

```python
from chongming_jwt import JWTAuth

config = {
    "enabled": True,
    "algorithm": "HS256",
    "secret_key": "your-secret-key",
    "issuer": "your-issuer",
    "audience": "your-audience",
    "user_id_claim": "sub",
    "roles_claim": "roles",
    "whitelist_paths": ["/health", "/public"],
}

jwt_auth = JWTAuth(config)
payload = jwt_auth.decode_token(token)
if payload:
    user_info = jwt_auth.get_user_info(payload)
