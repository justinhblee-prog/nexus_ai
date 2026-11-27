"""Small, testable password gate for the Streamlit entry point."""
import hmac
import os


def auth_enabled(value=None):
    setting = os.getenv("NEXUS_AUTH_ENABLED", "false") if value is None else value
    return str(setting).strip().lower() in {"1", "true", "yes", "on"}


def configured_password(value=None):
    password = os.getenv("NEXUS_API_PASSWORD", "") if value is None else value
    return password if isinstance(password, str) and len(password) >= 12 else ""


def is_auth_configured():
    return bool(configured_password())


def verify_streamlit_password(candidate, expected=None):
    expected_password = configured_password(expected)
    if not expected_password or not isinstance(candidate, str):
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected_password.encode("utf-8"))
