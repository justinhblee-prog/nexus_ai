"""Supabase Hosted Auth token validation for NEXUS.

This module validates Supabase-issued access tokens using the project's JWKS.
It never accepts caller-supplied user IDs as authorization context and never
loads or exposes a service-role key.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Mapping


class HostedAuthError(ValueError):
    """Raised when a hosted access token is invalid or lacks required claims."""


class HostedAuthConfigurationError(RuntimeError):
    """Raised when hosted auth is enabled without safe public/JWKS configuration."""


def _enabled(env: Mapping[str, str]) -> bool:
    return env.get("NEXUS_HOSTED_AUTH_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def is_hosted_auth_enabled() -> bool:
    return _enabled(os.environ)


def _supabase_url(env: Mapping[str, str]) -> str:
    url = env.get("NEXUS_SUPABASE_URL", "").strip().rstrip("/")
    if not url.startswith("https://") or any(ch.isspace() for ch in url):
        raise HostedAuthConfigurationError("NEXUS_SUPABASE_URL must be an HTTPS URL")
    return url


def _is_service_role_key(value: str) -> bool:
    if value.lower().startswith(("service_role", "sb_secret_")):
        return True
    parts = value.split(".")
    if len(parts) != 3:
        return False
    try:
        payload = parts[1] + ("=" * (-len(parts[1]) % 4))
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return claims.get("role") == "service_role"
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return False


def public_auth_config(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only the browser-safe project URL and publishable key."""
    values = os.environ if env is None else env
    if not _enabled(values):
        raise HostedAuthConfigurationError("Hosted authentication is disabled")
    url = _supabase_url(values)
    publishable_key = values.get("NEXUS_SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not publishable_key or _is_service_role_key(publishable_key):
        raise HostedAuthConfigurationError("A Supabase publishable key is required; service-role keys are forbidden")
    return {"supabase_url": url, "publishable_key": publishable_key}


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HostedAuthError("Bearer access token is required")
    scheme, separator, token = authorization.strip().partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HostedAuthError("Bearer access token is required")
    return token.strip()


def verify_access_token(
    token: str,
    env: Mapping[str, str] | None = None,
    jwks_client=None,
    jwt_module=None,
) -> dict:
    """Verify signature, issuer, audience, expiry, subject and authenticated role."""
    values = os.environ if env is None else env
    if not _enabled(values):
        raise HostedAuthConfigurationError("Hosted authentication is disabled")
    url = _supabase_url(values)
    issuer = values.get("NEXUS_SUPABASE_JWT_ISSUER", f"{url}/auth/v1").strip().rstrip("/")
    jwks_url = values.get(
        "NEXUS_SUPABASE_JWKS_URL", f"{issuer}/.well-known/jwks.json"
    ).strip()
    audience = values.get("NEXUS_SUPABASE_JWT_AUDIENCE", "authenticated").strip()
    if not issuer.startswith("https://") or not jwks_url.startswith("https://") or not audience:
        raise HostedAuthConfigurationError("Supabase issuer, JWKS URL, and audience must be configured safely")

    if jwt_module is None:
        try:
            import jwt as jwt_module
        except ImportError as exc:
            raise HostedAuthConfigurationError("Install the pinned PyJWT[crypto] dependency") from exc

    try:
        client = jwks_client or jwt_module.PyJWKClient(jwks_url, cache_keys=True)
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt_module.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience=audience,
            issuer=issuer,
            leeway=30,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "role"]},
        )
    except Exception as exc:
        raise HostedAuthError("Supabase access token validation failed") from exc

    try:
        user_id = str(uuid.UUID(str(claims.get("sub", ""))))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HostedAuthError("Supabase access token subject is invalid") from exc
    if claims.get("role") != "authenticated":
        raise HostedAuthError("Supabase access token does not represent an authenticated user")
    if claims.get("iss", "").rstrip("/") != issuer:
        raise HostedAuthError("Supabase access token issuer mismatch")

    # Return only the minimum verified identity fields needed by application code.
    return {"user_id": user_id, "email": claims.get("email"), "role": "authenticated"}
