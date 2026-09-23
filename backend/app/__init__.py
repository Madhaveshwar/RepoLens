"""Backend application package."""
# This file makes `app` a Python package so that `uvicorn app.main:app`
# and absolute imports like `from app.config import settings` work
# when the application runs from the `backend/` directory (e.g. Render).
