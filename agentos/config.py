from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    providers_file: Path
    host: str
    port: int
    api_token: str
    fallbacks: tuple[str, ...]
    gateway_retries: int
    gateway_timeout: float

    @classmethod
    def load(cls) -> Settings:
        state_dir = Path(os.getenv("AGENTOS_STATE_DIR", "./var"))
        config_file = Path(os.getenv("AGENTOS_CONFIG_FILE", "/etc/agentos/config.json"))
        raw = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        gateway = raw.get("gateway", {})
        fallbacks_raw = os.getenv("AGENTOS_GATEWAY_FALLBACKS", "") or ",".join(
            gateway.get("fallbacks", [])
        )
        return cls(
            state_dir=state_dir,
            providers_file=Path(
                os.getenv("AGENTOS_PROVIDERS_FILE", "/etc/agentos/providers.json")
            ),
            host=os.getenv("AGENTOS_LISTEN_HOST", str(raw.get("listen_host", "127.0.0.1"))),
            port=int(os.getenv("AGENTOS_LISTEN_PORT", str(raw.get("listen_port", 7788)))),
            api_token=os.getenv("AGENTOS_API_TOKEN", str(raw.get("api_token", ""))),
            fallbacks=tuple(value.strip() for value in fallbacks_raw.split(",") if value.strip()),
            gateway_retries=int(gateway.get("retries", 2)),
            gateway_timeout=float(gateway.get("timeout_seconds", 120)),
        )
