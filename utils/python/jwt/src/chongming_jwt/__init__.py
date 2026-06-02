"""
chongming-jwt: JWT authentication utility for chongming gateway.

Provides JWTAuth class for creating, decoding and validating JWT tokens
with support for HMAC, RSA, and JWKS-based verification.
"""

import logging
import time
from typing import Dict, Any, List, Optional, Union
import jwt
from jwt import PyJWKClient

logger = logging.getLogger("chongming.jwt")


class JWTAuth:
    """JWT authentication handler.

    Supports token creation and verification with:
    - HMAC (HS256/HS384/HS512)
    - RSA (RS256/RS384/RS512)
    - JWKS-based verification

    Also provides configurable issuer, audience, user info extraction,
    and path whitelisting for the gateway.
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get("enabled", False)
        if not self.enabled:
            return
        self.algorithm = config.get("algorithm", "HS256")
        self.secret_key = config.get("secret_key")
        self.private_key_path = config.get("private_key_path")
        self.public_key_path = config.get("public_key_path")
        self.jwks_url = config.get("jwks_url")
        self.issuer = config.get("issuer")
        self.audience = config.get("audience")
        self.user_id_claim = config.get("user_id_claim", "sub")
        self.roles_claim = config.get("roles_claim", "roles")
        self.whitelist_paths = config.get("whitelist_paths", [])
        self.token_expire_seconds = config.get("token_expire_seconds", 3600)

        self.jwks_client = None
        if self.jwks_url:
            self.jwks_client = PyJWKClient(self.jwks_url)

        self.public_key = None
        if self.public_key_path:
            with open(self.public_key_path, "r") as f:
                self.public_key = f.read()

        self.private_key = None
        if self.private_key_path:
            with open(self.private_key_path, "r") as f:
                self.private_key = f.read()

    # ──────────────────────────────────────────────
    # Token Creation
    # ──────────────────────────────────────────────

    def create_token(
        self,
        payload: Dict[str, Any],
        expires_in: Optional[int] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Optional[str]:
        """Create a signed JWT token.

        Args:
            payload: Custom claims to include in the token (e.g., user data).
            expires_in: Token expiration time in seconds (default: from config,
                        or 3600 if not set). Pass 0 or None for no expiration.
            issuer: Override the configured issuer claim ('iss').
            audience: Override the configured audience claim ('aud').
            subject: Subject claim ('sub'), overrides 'sub' in payload if set.

        Returns:
            Encoded JWT token string, or None if creation fails (e.g., disabled
            or missing signing key).

        Raises:
            jwt.PyJWTError: If token signing fails due to key/algorithm issues.

        Example:
            >>> auth = JWTAuth({"enabled": True, "secret_key": "mykey", "algorithm": "HS256"})
            >>> token = auth.create_token({"user_id": "123", "roles": ["admin"]})
        """
        if not self.enabled:
            logger.warning("JWT auth is disabled, cannot create token")
            return None

        # Build claims from payload first
        now = int(time.time())
        claims: Dict[str, Any] = dict(payload)

        # Standard claims are set AFTER merging payload, so they always take precedence
        # (preventing payload from accidentally overriding required standard fields)

        # Add issuer
        iss = issuer or self.issuer
        if iss:
            claims["iss"] = iss

        # Add audience
        aud = audience or self.audience
        if aud:
            claims["aud"] = aud

        # Add subject (from explicit 'subject' param, then from payload 'sub',
        # then from user_id_claim field, then from common 'user_id' key)
        sub = subject
        if not sub:
            sub = payload.get("sub")
        if not sub:
            # If user_id_claim points to a different key, check that
            if self.user_id_claim and self.user_id_claim != "sub":
                sub = payload.get(self.user_id_claim)
        if not sub:
            # Fallback: common "user_id" key
            sub = payload.get("user_id")
        if sub:
            claims["sub"] = str(sub)

        # Add issued-at and expiration
        claims["iat"] = now
        expire = expires_in if expires_in is not None else self.token_expire_seconds
        if expire:
            claims["exp"] = now + expire

        # Sign the token
        try:
            if self.algorithm.startswith("HS"):
                # HMAC signing
                if not self.secret_key:
                    logger.error("secret_key is required for HMAC algorithm %s", self.algorithm)
                    return None
                token = jwt.encode(claims, self.secret_key, algorithm=self.algorithm)

            elif self.algorithm.startswith("RS"):
                # RSA signing
                if not self.private_key:
                    logger.error(
                        "private_key is required for RSA algorithm %s. "
                        "Set 'private_key_path' in config.", self.algorithm
                    )
                    return None
                token = jwt.encode(claims, self.private_key, algorithm=self.algorithm)

            elif self.algorithm.startswith("ES"):
                # ECDSA signing
                if not self.private_key:
                    logger.error(
                        "private_key is required for EC algorithm %s. "
                        "Set 'private_key_path' in config.", self.algorithm
                    )
                    return None
                token = jwt.encode(claims, self.private_key, algorithm=self.algorithm)

            elif self.algorithm.startswith("Ed"):
                # EdDSA signing
                if not self.private_key:
                    logger.error(
                        "private_key is required for EdDSA algorithm %s. "
                        "Set 'private_key_path' in config.", self.algorithm
                    )
                    return None
                token = jwt.encode(claims, self.private_key, algorithm=self.algorithm)

            else:
                logger.error("Unsupported algorithm for signing: %s", self.algorithm)
                return None

            logger.info(
                "Created JWT token for subject='%s' (alg=%s, exp=%s)",
                claims.get("sub", "(none)"), self.algorithm,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims["exp"])) if "exp" in claims else "never",
            )
            return token

        except jwt.PyJWTError as e:
            logger.error("Failed to create JWT token: %s", e)
            raise

    # ──────────────────────────────────────────────
    # Token Decoding / Verification
    # ──────────────────────────────────────────────

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
                    token, self.secret_key, algorithms=[self.algorithm], # type: ignore
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
                    token, self.public_key, algorithms=[self.algorithm], # type: ignore
                    issuer=self.issuer, audience=self.audience,
                )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT: {e}")
        return None

    # ──────────────────────────────────────────────
    # User Info Extraction
    # ──────────────────────────────────────────────

    def get_user_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract user info (user_id, roles) from decoded JWT payload."""
        user_id = payload.get(self.user_id_claim, "")
        roles = payload.get(self.roles_claim, [])
        if not isinstance(roles, list):
            roles = [roles] if roles else []
        return {"user_id": str(user_id), "roles": roles}

    # ──────────────────────────────────────────────
    # Path Whitelist
    # ──────────────────────────────────────────────

    def is_whitelisted(self, path: str) -> bool:
        """Check if a path is whitelisted (bypasses JWT auth)."""
        if not self.enabled:
            return True
        for pattern in self.whitelist_paths:
            if path.startswith(pattern):
                return True
        return False


__all__ = ["JWTAuth"]
