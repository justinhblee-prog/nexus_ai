"""Vercel FastAPI entrypoint for the authenticated hosted studio.

The Streamlit desktop app remains in app.py. Vercel is explicitly routed to this
ASGI entrypoint and always runs in hosted-auth mode; local operator APIs stay
disabled on the public deployment.
"""
import os

os.environ["NEXUS_HOSTED_AUTH_ENABLED"] = "true"

from api_server import app  # noqa: E402
