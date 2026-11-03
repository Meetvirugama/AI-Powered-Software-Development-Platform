"""Root entry point for AI-Powered Software Development Platform.

Supports standard local dev runners (uvicorn main:app) and Azure App Service
default entry points without requiring custom PYTHONPATH flags.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path so app and its packages resolve cleanly
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app  # noqa: F401, E402

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)
