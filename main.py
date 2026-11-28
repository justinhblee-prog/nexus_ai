"""Standard Vercel FastAPI entrypoint.

Vercel's Python runtime reliably discovers a root-level ``main.py``. Keep the
hosted-mode guard in ``vercel_entrypoint`` so this alias never exposes the
legacy local operator API on a hosted deployment.
"""
from vercel_entrypoint import app

__all__ = ["app"]
