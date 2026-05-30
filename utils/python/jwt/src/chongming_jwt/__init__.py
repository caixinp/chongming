"""
chongming-jwt: JWT authentication utility for chongming gateway.

Provides JWTAuth class for decoding and validating JWT tokens
with support for HMAC, RSA, and JWKS-based verification.
"""

import logging
from typing import Dict, Any, List, Optional
import jwt
from jwt import PyJWKClient

logger = logging.getLogger("chongming.jwt")


class JWTAuth:
    """JWT authentication handler.

    Supports HMAC (HS256/HS384/HS512), RSA (RS256/RS384/RS512),
    and JWKS-based verification with configurable issuer, audience,
    user info extraction, and path whitelisting.
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get("enabled", False)
        if not self.enabled:
            return
        self.algorithm = config.get("algorithm", "HS256")
        self.secret_key = config.get("secret_key")
        self.public_key_path = config.get("public_key_path")
        self.jwks_url = config.get("jwks_url")
        self.issuer = config.get("issuer")
        self.audience = config.get("audience")
        self.user_id_claim = config.get("user_id_claim", "sub")
        self.roles_claim = config.get("roles_claim", "roles")
        self.whitelist_paths = config.get("whitelist_paths", [])

        self.jwks_client = None
        if self.jwks_url:
            self.jwks_client = PyJWKClient(self.jwks_url)

        self.public_key = None
        if self.public_key_path:
            with open(self.public_key_path, "r") as f:
                self.public_key = f.read()

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode and validate a JWT token.

        Returns the decoded payload if valid, or None if the token
        is expired, invalid, or JWT auth is disabled.
        """
        if not self.enabled:
            return {}
        try:
            if self.algorithm.startswith("HS"):
                payload = jwt.decode(
                    token, self.secret_key, algorithms=[self.algorithm],
                    issuer=self.issuer, audience=self.audience,
                )
            elif self.jwks_client:
                signing_key = self.jwks_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token, signing_key.key, algorithms=[self.algorithm],
                    issuer=self.issuer, audience=self.audience,
                )
            else:
                payload = jwt.decode(
                    token, self.public_key, algorithms=[self.algorithm],
                    issuer=self.issuer, audience=self.audience,
                )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT: {e}")
        return None

    def get_user_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract user info (user_id, roles) from decoded JWT payload."""
        user_id = payload.get(self.user_id_claim, "")
        roles = payload.get(self.roles_claim, [])
        if not isinstance(roles, list):
            roles = [roles] if roles else []
        return {"user_id": str(user_id), "roles": roles}

    def is_whitelisted(self, path: str) -> bool:
        """Check if a path is whitelisted (bypasses JWT auth)."""
        if not self.enabled:
            return True
        for pattern in self.whitelist_paths:
            if path.startswith(pattern):
                return True
        return False


__all__ = ["JWTAuth"]
