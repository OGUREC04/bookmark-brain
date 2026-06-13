"""Shared code reused by BOTH the bot and the backend worker.

Currently hosts media processing (STT, document extraction) extracted from the
bot so the FastAPI backend/worker can reuse it without importing ``bot.*``
(they are separate deployments). See bead bookmark-brain-3sr.

This package must NOT import from ``bot`` or ``app`` — it is the shared leaf.
Configuration (API keys, buckets) is injected by callers as arguments, never
read from a project-specific settings module here.
"""
