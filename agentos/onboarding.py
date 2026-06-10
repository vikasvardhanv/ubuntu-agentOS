from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path

from agentos.gateway.discovery import discover_models
from agentos.gateway.providers import BUILTIN_PROVIDERS, Provider, ProviderRegistry


CONFIG_DIR = Path("/etc/agentos")


def _choose(prompt: str, options: list[str]) -> str:
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option}")
    while True:
        value = input(f"{prompt}: ").strip()
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print("Choose a listed number.")


def _atomic_json(path: Path, value: dict, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _custom_provider() -> Provider:
    provider_id = input("Provider name: ").strip().lower()
    base_url = input("OpenAI-compatible base URL: ").strip().rstrip("/")
    local = input("Is this endpoint on this device? [y/N]: ").strip().lower() == "y"
    ProviderRegistry._validate_url(base_url, local)
    return Provider(provider_id, base_url, "CUSTOM_API_KEY", local=local)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("AgentOS provider setup must run through sudo.")

    print("\nConnect AgentOS to an LLM provider\n")
    choices = [*BUILTIN_PROVIDERS, "custom"]
    selected = _choose("Provider", choices)
    provider = _custom_provider() if selected == "custom" else BUILTIN_PROVIDERS[selected]
    secret = ""
    if provider.secret_env:
        secret = getpass.getpass("API key (stored only in the AgentOS gateway boundary): ").strip()
        if not secret:
            raise SystemExit("A credential is required for this provider.")

    print("Testing connection and discovering models...")
    models = discover_models(provider, secret)
    if not models:
        raise SystemExit("The provider returned no available models.")
    model = _choose("Default model", models)

    provider_entry = {
        "base_url": provider.base_url,
        "transport": provider.transport,
        "local": provider.local,
        "capabilities": sorted(provider.capabilities),
        "secret_env": provider.secret_env,
        "metadata": provider.metadata,
    }
    _atomic_json(
        CONFIG_DIR / "providers.json",
        {"selected_route": f"{provider.id}:{model}", "providers": {provider.id: provider_entry}},
        0o640,
    )
    _atomic_json(
        CONFIG_DIR / "secrets.json",
        {"providers": {provider.id: secret}} if secret else {"providers": {}},
        0o640,
    )
    print(f"\nConnected {provider.id}. AgentOS will route model='auto' to the selected model.")


if __name__ == "__main__":
    main()
