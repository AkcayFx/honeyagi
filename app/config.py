import math
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _env_number(name, default, convert):
    try:
        return convert(os.getenv(name, str(default)))
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be a valid number") from None


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("SAP_DB", "data/assessments.sqlite3")))
    token: str = field(default_factory=lambda: os.getenv("SAP_TOKEN") or secrets.token_urlsafe(32), repr=False)
    demo_origin: str = "http://127.0.0.1:8001"
    dashboard_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")
    tool_timeout: float = 5.0
    planner_timeout: float = field(default_factory=lambda: _env_number("SAP_PLANNER_TIMEOUT", 30, float))
    planner_provider: str = field(default_factory=lambda: os.getenv("SAP_PLANNER_PROVIDER", "fake"))
    planner_model: str = field(default_factory=lambda: os.getenv("SAP_PLANNER_MODEL", ""))
    planner_base_url: str = field(default_factory=lambda: os.getenv("SAP_PLANNER_BASE_URL", "https://api.openai.com/v1"))
    planner_api_key: str = field(default_factory=lambda: os.getenv("SAP_PLANNER_API_KEY", ""), repr=False)
    planner_response_format: str = field(default_factory=lambda: os.getenv("SAP_PLANNER_RESPONSE_FORMAT", "json_schema"))
    planner_max_tokens: int = field(default_factory=lambda: _env_number("SAP_PLANNER_MAX_TOKENS", 2048, int))

    def __post_init__(self):
        if len(self.token) < 24:
            raise ValueError("SAP_TOKEN must contain at least 24 characters")
        if not math.isfinite(self.planner_timeout) or not 0 < self.planner_timeout <= 120:
            raise ValueError("SAP_PLANNER_TIMEOUT must be greater than zero and at most 120 seconds")
        if self.planner_provider not in ("fake", "openai_compatible"):
            raise ValueError("SAP_PLANNER_PROVIDER must be fake or openai_compatible")
        if self.planner_response_format not in ("json_schema", "json_object"):
            raise ValueError("SAP_PLANNER_RESPONSE_FORMAT must be json_schema or json_object")
        if not 128 <= self.planner_max_tokens <= 4096:
            raise ValueError("SAP_PLANNER_MAX_TOKENS must be between 128 and 4096")
        if self.planner_provider == "fake":
            return  # Offline mode makes no provider request and needs no credentials.
        if not re.fullmatch(r"[a-zA-Z0-9._/-]{1,100}", self.planner_model):
            raise ValueError("Set SAP_PLANNER_MODEL to a valid explicit model identifier")
        try:
            value = self.planner_base_url
            if any(ord(c) <= 32 or ord(c) > 126 for c in value) or any(c in value for c in r"\?#%"):
                raise ValueError
            url = urlsplit(value)
            if (not url.hostname or url.username is not None or url.password is not None
                    or url.scheme not in ("http", "https")
                    or any(part in (".", "..") for part in url.path.split("/"))
                    or (url.port is not None and not 1 <= url.port <= 65535)):
                raise ValueError
            loopback = url.hostname in ("127.0.0.1", "localhost", "::1")
            if url.scheme == "http" and not loopback:
                raise ValueError
        except ValueError:
            # Never reflect a URL that might contain credentials into a traceback.
            raise ValueError("SAP_PLANNER_BASE_URL needs HTTPS, or HTTP on an exact loopback host, without credentials/query/fragment") from None
        if not self.planner_api_key and not loopback:
            raise ValueError("Set SAP_PLANNER_API_KEY for a remote planner; offline mode remains available")
        if self.planner_api_key and (len(self.planner_api_key) > 512 or any(not 33 <= ord(c) <= 126 for c in self.planner_api_key)):
            raise ValueError("SAP_PLANNER_API_KEY must be a bounded printable header value")
