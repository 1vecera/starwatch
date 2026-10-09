"""Settings and credentials.

Credentials come from the environment. Daniel's managed shells already export them; a local `.env`
(never committed) is read as a fallback. Each credential has one canonical name the code uses and
a few accepted aliases. Values are never logged or sent to the browser, only their presence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Canonical name -> accepted environment variable names, first match wins.
CREDENTIALS: dict[str, tuple[str, ...]] = {
    "APIFY_TOKEN": ("APIFY_TOKEN", "DAS_ITEM_APIFY__APIFY_TOKEN"),
    "ELEVENLABS_API_KEY": (
        "ELEVENLABS_API_KEY",
        "ELEVEN_LABS_STT_TOKEN",
        "DAS_ITEM_ELEVENLABS__ELEVEN_LABS_STT_TOKEN",
    ),
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY",),
}


class MissingCredential(RuntimeError):
    """A step needs a credential that is not set. The runner reports the step as skipped."""

    def __init__(self, name: str):
        super().__init__(f"{name} is not set")
        self.name = name


@dataclass
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    # Seconds each step waits before finishing. Only for UI work on stub steps; the screen labels it.
    step_pause_s: float = 0.0
    _credentials: dict[str, str | None] = field(default_factory=dict, repr=False)

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "starwatch.sqlite3"

    def credential(self, name: str) -> str:
        value = self._credentials.get(name)
        if not value:
            raise MissingCredential(name)
        return value

    def credential_presence(self) -> dict[str, bool]:
        return {name: bool(self._credentials.get(name)) for name in CREDENTIALS}

    def missing_credentials(self) -> list[str]:
        return [name for name, present in self.credential_presence().items() if not present]


def _read_credentials() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for name, aliases in CREDENTIALS.items():
        found[name] = next((os.environ[a] for a in aliases if os.environ.get(a)), None)
    return found


def load_settings(**overrides) -> Settings:
    load_dotenv(override=False)
    settings = Settings(
        data_dir=Path(os.environ.get("STARWATCH_DATA_DIR", "data")).resolve(),
        host=os.environ.get("STARWATCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("STARWATCH_PORT", "8000")),
        step_pause_s=float(os.environ.get("STARWATCH_STEP_PAUSE_S", "0")),
        _credentials=_read_credentials(),
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings
