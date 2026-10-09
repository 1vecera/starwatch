"""`uv run starwatch` starts the app on http://127.0.0.1:8000 (STARWATCH_PORT to change)."""

from __future__ import annotations

import logging
import os

import uvicorn

from .config import load_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    missing = settings.missing_credentials()
    print(f"Starwatch on http://{settings.host}:{settings.port}  data in {settings.data_dir}")
    print("Credentials missing: " + (", ".join(missing) if missing else "none"))
    uvicorn.run(
        "starwatch.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=os.environ.get("STARWATCH_RELOAD") == "1",
    )


if __name__ == "__main__":
    main()
