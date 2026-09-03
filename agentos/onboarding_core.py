"""Shared onboarding logic used by both the terminal wizard (``agentos.onboarding``)
and the GUI first-boot wizard (``packaging/firstboot/agentos-onboarding-gui``).

Keeping this here means both front-ends write the exact same
``/etc/agentos/providers.json`` / ``/etc/agentos/secrets.json`` shape and share
the same validation, model-discovery, and runtime-restart behaviour.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from agentos.gateway.discovery import discover_models
from agentos.gateway.errors import GatewayUpstreamError
from agentos.gateway.providers import BUILTIN_PROVIDERS, Provider, ProviderRegistry

CONFIG_DIR = Path("/etc/agentos")
STATE_DIR = Path(os.environ.get("AGENTOS_STATE_DIR", "/var/lib/agentos"))
AUTOSTART_DESKTOP_FILE = Path("/etc/xdg/autostart/agentos-onboarding.desktop")


class OnboardingError(Exception):
    """A user-facing onboarding failure with a friendly, actionable message."""


def atomic_json(path: Path, value: dict, mode: int) -> None:
    """Write JSON atomically with a temp-file + rename so readers never see partial data."""
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
            try:
                os.unlink(temporary)
            except OSError:
                pass


def builtin_providers() -> dict[str, Provider]:
    """All providers AgentOS knows how to talk to out of the box."""
    return dict(BUILTIN_PROVIDERS)


def with_base_url(provider: Provider, base_url: str) -> Provider:
    """Return a copy of ``provider`` pointed at a custom base URL (validated)."""
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        return provider
    try:
        ProviderRegistry._validate_url(base_url, provider.local)
    except ValueError as exc:
        raise OnboardingError(str(exc)) from exc
    return replace(provider, base_url=base_url)


def custom_provider(provider_id: str, base_url: str, local: bool) -> Provider:
    """Build a ``Provider`` for an arbitrary OpenAI-compatible / custom endpoint."""
    provider_id = provider_id.strip().lower()
    if not provider_id or not provider_id.isidentifier():
        raise OnboardingError(
            "Provider name must be a non-empty identifier (letters, digits, underscores)."
        )
    base_url = base_url.strip().rstrip("/")
    try:
        ProviderRegistry._validate_url(base_url, local)
    except ValueError as exc:
        raise OnboardingError(f"Invalid URL: {exc}") from exc
    return Provider(provider_id, base_url, "CUSTOM_API_KEY", local=local)


def discover(provider: Provider, secret: str) -> list[str]:
    """Discover available models, raising ``OnboardingError`` with a friendly message."""
    try:
        models = discover_models(provider, secret)
    except GatewayUpstreamError as exc:
        kind = getattr(exc, "kind", None)
        status = getattr(exc, "status", None)
        if kind and kind.value == "auth":
            raise OnboardingError(
                f"Authentication failed (HTTP {status}). Check your API key and try again."
            ) from exc
        if kind and kind.value == "billing":
            raise OnboardingError(
                "Billing issue detected. Verify your account has an active plan."
            ) from exc
        raise OnboardingError(f"Connection to {provider.id} failed: {exc}") from exc
    except OSError as exc:
        raise OnboardingError(
            f"Network error reaching {provider.id}: {exc}. "
            "Check that the provider is reachable and try again."
        ) from exc
    if not models:
        raise OnboardingError(
            f"{provider.id} is reachable but returned no available models. "
            "For Ollama: pull at least one model first (e.g. 'ollama pull llama3.2'). "
            "For vLLM: start the server with a model loaded."
        )
    return models


def write_provider_config(provider: Provider, model: str, secret: str) -> None:
    """Persist the selected provider + model + secret to /etc/agentos."""
    provider_entry = {
        "base_url": provider.base_url,
        "transport": provider.transport,
        "local": provider.local,
        "capabilities": sorted(provider.capabilities),
        "secret_env": provider.secret_env,
        "metadata": provider.metadata,
    }
    atomic_json(
        CONFIG_DIR / "providers.json",
        {"selected_route": f"{provider.id}:{model}", "providers": {provider.id: provider_entry}},
        mode=0o640,
    )
    atomic_json(
        CONFIG_DIR / "secrets.json",
        {"providers": {provider.id: secret}} if secret else {"providers": {}},
        mode=0o600,  # root-read-only — tighter than providers.json
    )
    # Ensure ownership and permissions are correct even on upgrades.
    os.chown(CONFIG_DIR / "providers.json", 0, -1)
    os.chown(CONFIG_DIR / "secrets.json", 0, -1)


def write_profile(name: str) -> None:
    """Persist the user's display name so the shell/launcher can greet them by it."""
    name = name.strip()
    atomic_json(CONFIG_DIR / "profile.json", {"name": name}, mode=0o644)


def mark_onboarding_complete() -> None:
    """Record that first-boot setup finished and remove the autostart entry."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "onboarding-complete").touch()
    try:
        AUTOSTART_DESKTOP_FILE.unlink()
    except FileNotFoundError:
        pass


_PULL_PERCENT_RE = re.compile(r"(\d+)\s*%")


def pull_ollama_model(model: str):
    """Run ``ollama pull <model>``, yielding ``(fraction, status_line)`` as it streams.

    ``fraction`` is ``0..1`` when a percentage can be parsed from Ollama's
    progress output, otherwise ``None``. Raises ``OnboardingError`` if the
    pull fails or the ``ollama`` binary is missing.
    """
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
    except FileNotFoundError as exc:
        raise OnboardingError("The 'ollama' command was not found on this system.") from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        match = _PULL_PERCENT_RE.search(line)
        fraction = int(match.group(1)) / 100 if match else None
        yield fraction, line

    proc.wait()
    if proc.returncode != 0:
        raise OnboardingError(f"'ollama pull {model}' failed (exit code {proc.returncode}).")


def restart_runtime() -> str:
    """Reload systemd and restart agentos-runtime if running under systemd.

    Returns a short human-readable status string.
    """
    if os.path.exists("/run/systemd/private"):
        try:
            subprocess.run(
                ["systemctl", "restart", "agentos-runtime.service"],
                check=True, capture_output=True,
            )
            return "agentos-runtime.service restarted."
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "Could not restart agentos-runtime.service — restart it manually."
    return "Not running under systemd — restart agentosd manually to apply changes."
