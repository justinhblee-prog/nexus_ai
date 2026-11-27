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
    except (AttributeError, ValueError, UnicodeError, json.JSONDecodeError):
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


def _verified_amr_entries(value):
    """Return only well-formed signed authentication-method timestamps."""
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if not isinstance(item, dict):
            continue
        method = item.get("method")
        timestamp = item.get("timestamp")
        if (
            isinstance(method, str)
            and 1 <= len(method) <= 64
            and isinstance(timestamp, (int, float))
            and not isinstance(timestamp, bool)
        ):
            entries.append({"method": method, "timestamp": int(timestamp)})
    return entries


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
        header = jwt_module.get_unverified_header(token)
    except Exception as exc:
        raise HostedAuthError("Supabase access token header is invalid") from exc

    if header.get("alg") == "HS256":
        # Supabase's legacy symmetric JWT secret has no public JWKS key. Follow
        # Supabase's documented verification path: ask Auth /user to validate
        # the token with the browser-safe publishable key.
        try:
            unverified_claims = jwt_module.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
            publishable_key = values.get("NEXUS_SUPABASE_PUBLISHABLE_KEY", "").strip()
            if not publishable_key or _is_service_role_key(publishable_key):
                raise HostedAuthConfigurationError("A safe Supabase publishable key is required for legacy token verification")
            import requests
            response = requests.get(
                f"{url}/auth/v1/user",
                headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if response.status_code != 200:
                raise HostedAuthError("Supabase Auth rejected the access token")
            user = response.json()
            user_id = str(uuid.UUID(str(user.get("id", ""))))
            claim_user_id = str(uuid.UUID(str(unverified_claims.get("sub", ""))))
            aud = unverified_claims.get("aud")
            if (
                user_id != claim_user_id
                or unverified_claims.get("role") != "authenticated"
                or unverified_claims.get("iss", "").rstrip("/") != issuer
                or not (audience in aud if isinstance(aud, list) else aud == audience)
            ):
                raise HostedAuthError("Supabase access token claims do not match the verified user")
            verified_user = {"user_id": user_id, "email": user.get("email"), "role": "authenticated"}
            amr = _verified_amr_entries(unverified_claims.get("amr"))
            if amr:
                verified_user["amr"] = amr
            return verified_user
        except HostedAuthError:
            raise
        except HostedAuthConfigurationError:
            raise
        except Exception as exc:
            raise HostedAuthError("Legacy Supabase access token validation failed") from exc

    try:
        client = jwks_client or jwt_module.PyJWKClient(jwks_url, cache_keys=True)
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt_module.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
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

    # Return only verified identity fields needed by application code. The
    # auth_time claim is used solely to enforce fresh reauthentication for deletion.
    verified_user = {"user_id": user_id, "email": claims.get("email"), "role": "authenticated"}
    amr = _verified_amr_entries(claims.get("amr"))
    if amr:
        verified_user["amr"] = amr
    return verified_user
