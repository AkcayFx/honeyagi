import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("SAP_DB", "data/assessments.sqlite3")))
    token: str = field(default_factory=lambda: os.getenv("SAP_TOKEN") or secrets.token_urlsafe(32))
    demo_origin: str = "http://127.0.0.1:8001"
    dashboard_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")
    tool_timeout: float = 5.0

    def __post_init__(self):
        if len(self.token) < 24:
            raise ValueError("SAP_TOKEN must contain at least 24 characters")
