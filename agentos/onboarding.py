from __future__ import annotations

import getpass
import os

from agentos.gateway.providers import BUILTIN_PROVIDERS
from agentos.onboarding_core import (
    OnboardingError,
    custom_provider,
    discover,
    restart_runtime,
    with_base_url,
    write_provider_config,
)


def _choose(prompt: str, options: list[str]) -> str:
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option}")
    while True:
        value = input(f"{prompt}: ").strip()
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print(f"  Enter a number between 1 and {len(options)}.")


def _prompt_local_url(provider):
    """For local providers (ollama, vllm) let the user override the base URL."""
    value = input(f"Base URL [{provider.base_url}]: ").strip()
    return with_base_url(provider, value) if value else provider


def _prompt_custom_provider():
    while True:
        provider_id = input("Provider name (e.g. 'my-llm'): ").strip().lower()
        base_url = input("OpenAI-compatible base URL (https://...): ").strip()
        local_flag = input("Is this endpoint on this device? [y/N]: ").strip().lower() == "y"
        try:
            return custom_provider(provider_id, base_url, local_flag)
        except OnboardingError as exc:
            print(f"  {exc}")


def _collect_api_key(provider) -> str:
    """Prompt for an API key with basic non-empty validation."""
    for attempt in range(3):
        secret = getpass.getpass(
            f"API key for {provider.id} (never written to disk in plain text): "
        ).strip()
        if secret:
            return secret
        print("  API key cannot be empty. Try again." if attempt < 2 else "")
    raise SystemExit("No valid API key provided after 3 attempts.")


def _try_discover_models(provider, secret) -> list[str]:
    print(f"\nTesting connection to {provider.id} and discovering models…")
    try:
        return discover(provider, secret)
    except OnboardingError as exc:
        raise SystemExit(str(exc)) from exc


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("AgentOS provider setup must run as root (via sudo).")

    print("\n╔══════════════════════════════════════════╗")
    print("║   AgentOS — Connect an LLM Provider      ║")
    print("╚══════════════════════════════════════════╝\n")

    choices = [*BUILTIN_PROVIDERS, "custom"]
    print("Available providers:")
    selected = _choose("Choose provider number", choices)

    if selected == "custom":
        provider = _prompt_custom_provider()
    elif selected in {"ollama", "vllm"}:
        # Local providers: no API key, but allow base URL override.
        provider = _prompt_local_url(BUILTIN_PROVIDERS[selected])
    else:
        provider = BUILTIN_PROVIDERS[selected]

    # Collect credential for cloud providers.
    secret = ""
    if provider.secret_env:
        secret = _collect_api_key(provider)

    # Discover models (exits with a message on failure).
    models = _try_discover_models(provider, secret)

    print(f"\nFound {len(models)} model(s). Choose a default:")
    model = _choose("Default model", models)

    write_provider_config(provider, model, secret)

    print(f"\n✓ Connected to {provider.id}.")
    print(f"  Default route: {provider.id}:{model}")
    print("  Use model='auto' in any API call to use this provider.\n")

    print(restart_runtime())


if __name__ == "__main__":
    main()
