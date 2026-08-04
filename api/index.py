"""Vercel serverless entrypoint. Vercel routes /api/* here (see vercel.json);
everything under public/ is served directly by the platform and never reaches
this function at all."""

from app.main import app  # noqa: F401
