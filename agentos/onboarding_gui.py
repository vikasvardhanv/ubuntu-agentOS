#!/usr/bin/env python3
"""AgentOS first-boot wizard — GTK4 + libadwaita.

A consumer-friendly, 3-click replacement for the terminal onboarding wizard
(``agentos.onboarding``). Three steps:

  1. Welcome  — "What should we call you?"
  2. Connect  — pick an agent/model provider from a simple gateway list
                (Local AI via Ollama is pre-selected and needs no API key;
                cloud providers like Claude/OpenAI/Gemini need an API key)
  3. Model    — pick the default model, then apply + finish

All writes go through ``agentos.onboarding_core`` so the GUI produces exactly
the same ``/etc/agentos/providers.json`` / ``secrets.json`` as the CLI wizard.
Must be run with permission to write to ``/etc/agentos`` (see
``packaging/firstboot/agentos-onboarding-gui``).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from agentos.gateway.providers import BUILTIN_PROVIDERS, Provider
from agentos.onboarding_core import (
    OnboardingError,
    custom_provider,
    discover,
    mark_onboarding_complete,
    pull_ollama_model,
    restart_runtime,
    write_profile,
    write_provider_config,
)

# Recommended small models that fit comfortably on consumer hardware and are
# good defaults for an offline-first install.
RECOMMENDED_OLLAMA_MODELS = [
    ("llama3.2:3b", "Meta Llama 3.2 (3B) — fast, great all-rounder"),
    ("qwen2.5:3b", "Qwen 2.5 (3B) — strong at coding & reasoning"),
    ("phi3.5", "Phi-3.5 Mini — tiny footprint, runs on modest hardware"),
]

# Order matters: local-first, then the most popular cloud agents, then the
# long tail. "custom" is handled separately (not in BUILTIN_PROVIDERS) and is
# always appended last so users can connect literally anything else.
PROVIDER_ORDER = [
    "ollama", "lmstudio", "vllm",
    "anthropic", "openai", "gemini", "grok", "openrouter",
    "deepseek", "mistral", "groq", "together", "fireworks", "cerebras",
    "moonshot", "zai", "minimax", "dashscope", "nous",
]

PROVIDER_LABELS: dict[str, tuple[str, str]] = {
    "ollama": ("Local AI (Ollama)", "Runs on this device. No account, no API key, fully offline."),
    "lmstudio": ("LM Studio (local)", "Connect to a local LM Studio server."),
    "vllm": ("vLLM (local server)", "Connect to a local vLLM OpenAI-compatible server."),
    "anthropic": ("Claude (Anthropic)", "State-of-the-art reasoning. Requires an Anthropic API key."),
    "openai": ("OpenAI", "GPT models. Requires an OpenAI API key."),
    "gemini": ("Gemini (Google)", "Requires a Gemini API key."),
    "grok": ("Grok (xAI)", "Requires an xAI API key."),
    "openrouter": ("OpenRouter", "Aggregates many providers. Requires an OpenRouter API key."),
    "deepseek": ("DeepSeek", "Requires a DeepSeek API key."),
    "mistral": ("Mistral", "Requires a Mistral API key."),
    "groq": ("Groq", "Ultra-fast inference. Requires a Groq API key."),
    "together": ("Together AI", "Aggregates many open models. Requires a Together API key."),
    "fireworks": ("Fireworks AI", "Requires a Fireworks API key."),
    "cerebras": ("Cerebras", "Ultra-fast inference. Requires a Cerebras API key."),
    "moonshot": ("Moonshot (Kimi)", "Requires a Moonshot API key."),
    "zai": ("Z.AI (GLM)", "Requires a Z.AI API key."),
    "minimax": ("MiniMax", "Requires a MiniMax API key."),
    "dashscope": ("Alibaba Qwen (DashScope)", "Requires a DashScope API key."),
    "nous": ("Nous Research", "Requires a Nous API key."),
    "custom": ("Other / custom provider", "Connect any OpenAI-compatible endpoint by URL."),
}


@dataclass
class WizardState:
    name: str = ""
    provider: Provider | None = None
    secret: str = ""
    models: list[str] = field(default_factory=list)
    model: str = ""


# ---------------------------------------------------------------------------
# Step 1 — Welcome
# ---------------------------------------------------------------------------

class WelcomePage(Adw.NavigationPage):
    def __init__(self, wizard: "WizardWindow") -> None:
        super().__init__(title="Welcome")
        self._wizard = wizard

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(48)
        box.set_margin_bottom(48)

        icon = Gtk.Image.new_from_icon_name("dev.agentos.Shell")
        icon.set_pixel_size(96)
        box.append(icon)

        title = Gtk.Label(label="Welcome to AgentOS")
        title.add_css_class("title-1")
        box.append(title)

        subtitle = Gtk.Label(label="Your computer, run by agents you talk to.")
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        self._entry = Gtk.Entry()
        self._entry.set_placeholder_text("What should we call you?")
        self._entry.set_width_chars(28)
        self._entry.set_halign(Gtk.Align.CENTER)
        self._entry.connect("activate", self._on_continue)
        self._entry.connect("changed", self._on_changed)
        box.append(self._entry)

        self._continue_btn = Gtk.Button(label="Continue")
        self._continue_btn.add_css_class("suggested-action")
        self._continue_btn.add_css_class("pill")
        self._continue_btn.set_halign(Gtk.Align.CENTER)
        self._continue_btn.set_sensitive(False)
        self._continue_btn.connect("clicked", self._on_continue)
        box.append(self._continue_btn)

        toolbar.set_content(box)
        self.set_child(toolbar)

    def _on_changed(self, entry: Gtk.Entry) -> None:
        self._continue_btn.set_sensitive(bool(entry.get_text().strip()))

    def _on_continue(self, *_args: Any) -> None:
        name = self._entry.get_text().strip()
        if not name:
            return
        self._wizard.state.name = name
        self._wizard.push(ConnectPage(self._wizard))


# ---------------------------------------------------------------------------
# Step 2 — Connect an agent (provider gateway picker)
# ---------------------------------------------------------------------------

class ConnectPage(Adw.NavigationPage):
    def __init__(self, wizard: "WizardWindow") -> None:
        super().__init__(title="Connect an Agent")
        self._wizard = wizard
        self._rows: dict[str, Adw.ActionRow] = {}
        self._key_rows: dict[str, Adw.PasswordEntryRow] = {}
        self._custom_name_row: Adw.EntryRow | None = None
        self._custom_url_row: Adw.EntryRow | None = None
        self._custom_local_row: Adw.SwitchRow | None = None
        self._group = None
        self._selected = "ollama"

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)

        heading = Gtk.Label(label=f"Hi {wizard.state.name}, how should agents think?")
        heading.add_css_class("title-2")
        heading.set_xalign(0)
        outer.append(heading)

        sub = Gtk.Label(
            label="Pick one to start. You can connect more agents later in Settings."
        )
        sub.add_css_class("dim-label")
        sub.set_xalign(0)
        outer.append(sub)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        group = Adw.PreferencesGroup()

        for provider_id in PROVIDER_ORDER:
            if provider_id not in BUILTIN_PROVIDERS:
                continue
            title, subtitle = PROVIDER_LABELS.get(provider_id, (provider_id, ""))
            row = Adw.ActionRow(title=title, subtitle=subtitle)

            radio = Gtk.CheckButton()
            if self._group is None:
                self._group = radio
            else:
                radio.set_group(self._group)
            radio.set_active(provider_id == "ollama")
            radio.set_valign(Gtk.Align.CENTER)
            radio.connect("toggled", self._on_select, provider_id)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)

            provider = BUILTIN_PROVIDERS[provider_id]
            if provider.secret_env:
                key_row = Adw.PasswordEntryRow(title=f"{title} API key")
                self._key_rows[provider_id] = key_row
                key_revealer = Gtk.Revealer()
                key_revealer.set_child(key_row)
                key_revealer.set_reveal_child(False)
                row._key_revealer = key_revealer  # type: ignore[attr-defined]

            self._rows[provider_id] = row
            group.add(row)
            if provider.secret_env:
                group.add(key_revealer)

        # "Custom" — connect any OpenAI-compatible endpoint by URL, for
        # providers AgentOS doesn't know about yet.
        custom_title, custom_subtitle = PROVIDER_LABELS["custom"]
        custom_row = Adw.ActionRow(title=custom_title, subtitle=custom_subtitle)
        custom_radio = Gtk.CheckButton()
        if self._group is None:
            self._group = custom_radio
        else:
            custom_radio.set_group(self._group)
        custom_radio.set_valign(Gtk.Align.CENTER)
        custom_radio.connect("toggled", self._on_select, "custom")
        custom_row.add_prefix(custom_radio)
        custom_row.set_activatable_widget(custom_radio)
        self._rows["custom"] = custom_row

        custom_fields = Adw.PreferencesGroup()
        self._custom_name_row = Adw.EntryRow(title="Provider name (e.g. my-llm)")
        custom_fields.add(self._custom_name_row)
        self._custom_url_row = Adw.EntryRow(title="Base URL (https://api.example.com/v1)")
        custom_fields.add(self._custom_url_row)
        self._custom_local_row = Adw.SwitchRow(
            title="Running on this device", subtitle="Allows a plain http:// URL"
        )
        custom_fields.add(self._custom_local_row)
        self._key_rows["custom"] = Adw.PasswordEntryRow(title="API key (optional)")
        custom_fields.add(self._key_rows["custom"])

        custom_revealer = Gtk.Revealer()
        custom_revealer.set_child(custom_fields)
        custom_revealer.set_reveal_child(False)
        custom_row._key_revealer = custom_revealer  # type: ignore[attr-defined]

        group.add(custom_row)
        group.add(custom_revealer)

        scroll.set_child(group)
        outer.append(scroll)

        self._status = Gtk.Label(label="")
        self._status.add_css_class("error")
        self._status.set_visible(False)
        outer.append(self._status)

        self._continue_btn = Gtk.Button(label="Connect & Continue")
        self._continue_btn.add_css_class("suggested-action")
        self._continue_btn.add_css_class("pill")
        self._continue_btn.set_halign(Gtk.Align.END)
        self._continue_btn.connect("clicked", self._on_continue)
        outer.append(self._continue_btn)

        self._spinner = Gtk.Spinner()
        outer.append(self._spinner)

        toolbar.set_content(outer)
        self.set_child(toolbar)
        self._update_reveal()

    def _on_select(self, radio: Gtk.CheckButton, provider_id: str) -> None:
        if radio.get_active():
            self._selected = provider_id
            self._update_reveal()

    def _update_reveal(self) -> None:
        for provider_id, row in self._rows.items():
            revealer = getattr(row, "_key_revealer", None)
            if revealer is not None:
                revealer.set_reveal_child(provider_id == self._selected)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._continue_btn.set_sensitive(not busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._status.set_visible(bool(message))
        self._status.set_label(message)

    def _on_continue(self, *_args: Any) -> None:
        provider_id = self._selected

        if provider_id == "custom":
            name = self._custom_name_row.get_text().strip() if self._custom_name_row else ""
            url = self._custom_url_row.get_text().strip() if self._custom_url_row else ""
            local = bool(self._custom_local_row.get_active()) if self._custom_local_row else False
            if not name or not url:
                self._set_busy(False, "Enter a provider name and base URL.")
                return
            try:
                provider = custom_provider(name, url, local)
            except OnboardingError as exc:
                self._set_busy(False, str(exc))
                return
            secret = self._key_rows["custom"].get_text().strip()
        else:
            provider = BUILTIN_PROVIDERS[provider_id]
            secret = ""
            if provider.secret_env:
                key_row = self._key_rows.get(provider_id)
                secret = key_row.get_text().strip() if key_row else ""
                if not secret:
                    self._set_busy(False, f"Enter an API key for {PROVIDER_LABELS[provider_id][0]}.")
                    return

        self._set_busy(True, "Connecting…")
        threading.Thread(
            target=self._connect_bg, args=(provider, secret), daemon=True
        ).start()

    def _connect_bg(self, provider: Provider, secret: str) -> None:
        # For local Ollama, make sure at least one model is available, pulling
        # a small recommended default if the user has none yet.
        if provider.id == "ollama":
            try:
                models = discover(provider, secret)
            except OnboardingError:
                models = []
            if not models:
                default_model = RECOMMENDED_OLLAMA_MODELS[0][0]
                GLib.idle_add(self._set_busy, True, f"Downloading {default_model} (first run only)…")
                try:
                    for fraction, line in pull_ollama_model(default_model):
                        pct = f"{int(fraction * 100)}%" if fraction is not None else "…"
                        GLib.idle_add(
                            self._set_busy, True, f"Downloading {default_model}: {pct}"
                        )
                except OnboardingError as exc:
                    GLib.idle_add(self._set_busy, False, str(exc))
                    return

        try:
            models = discover(provider, secret)
        except OnboardingError as exc:
            GLib.idle_add(self._set_busy, False, str(exc))
            return

        def _proceed() -> bool:
            self._set_busy(False)
            self._wizard.state.provider = provider
            self._wizard.state.secret = secret
            self._wizard.state.models = models
            self._wizard.push(ModelPage(self._wizard))
            return False

        GLib.idle_add(_proceed)


# ---------------------------------------------------------------------------
# Step 3 — Pick a default model
# ---------------------------------------------------------------------------

class ModelPage(Adw.NavigationPage):
    def __init__(self, wizard: "WizardWindow") -> None:
        super().__init__(title="Choose a Model")
        self._wizard = wizard
        self._selected = wizard.state.models[0] if wizard.state.models else ""

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)

        provider = wizard.state.provider
        provider_name = PROVIDER_LABELS.get(provider.id, (provider.id, ""))[0] if provider else "?"
        heading = Gtk.Label(label=f"Connected to {provider_name}")
        heading.add_css_class("title-2")
        heading.set_xalign(0)
        outer.append(heading)

        sub = Gtk.Label(label="Pick the default model for AgentOS to use.")
        sub.add_css_class("dim-label")
        sub.set_xalign(0)
        outer.append(sub)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        group = Adw.PreferencesGroup()
        radio_group = None
        for model in wizard.state.models:
            row = Adw.ActionRow(title=model)
            radio = Gtk.CheckButton()
            if radio_group is None:
                radio_group = radio
            else:
                radio.set_group(radio_group)
            radio.set_active(model == self._selected)
            radio.set_valign(Gtk.Align.CENTER)
            radio.connect("toggled", self._on_select, model)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            group.add(row)
        scroll.set_child(group)
        outer.append(scroll)

        finish_btn = Gtk.Button(label="Finish setup")
        finish_btn.add_css_class("suggested-action")
        finish_btn.add_css_class("pill")
        finish_btn.set_halign(Gtk.Align.END)
        finish_btn.set_sensitive(bool(self._selected))
        finish_btn.connect("clicked", self._on_finish)
        outer.append(finish_btn)

        self._status = Gtk.Label(label="")
        outer.append(self._status)

        toolbar.set_content(outer)
        self.set_child(toolbar)
        self._finish_btn = finish_btn

    def _on_select(self, radio: Gtk.CheckButton, model: str) -> None:
        if radio.get_active():
            self._selected = model
            self._finish_btn.set_sensitive(True)

    def _on_finish(self, *_args: Any) -> None:
        self._wizard.state.model = self._selected
        self._finish_btn.set_sensitive(False)
        self._status.set_label("Applying configuration…")
        threading.Thread(target=self._apply_bg, daemon=True).start()

    def _apply_bg(self) -> None:
        state = self._wizard.state
        write_profile(state.name)
        write_provider_config(state.provider, state.model, state.secret)
        status = restart_runtime()
        mark_onboarding_complete()

        def _proceed() -> bool:
            self._wizard.push(DonePage(self._wizard, status))
            return False

        GLib.idle_add(_proceed)


# ---------------------------------------------------------------------------
# Step 4 — Done
# ---------------------------------------------------------------------------

class DonePage(Adw.NavigationPage):
    def __init__(self, wizard: "WizardWindow", status: str) -> None:
        super().__init__(title="All Set")
        self._wizard = wizard

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(48)
        box.set_margin_bottom(48)

        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        icon.set_pixel_size(96)
        icon.add_css_class("success")
        box.append(icon)

        provider = wizard.state.provider
        provider_name = PROVIDER_LABELS.get(provider.id, (provider.id, ""))[0] if provider else "?"

        title = Gtk.Label(label=f"You're ready, {wizard.state.name}!")
        title.add_css_class("title-1")
        box.append(title)

        sub = Gtk.Label(
            label=f"AgentOS is connected to {provider_name} ({wizard.state.model}).\n"
            "Open the chat bar anytime and just ask."
        )
        sub.add_css_class("dim-label")
        sub.set_justify(Gtk.Justification.CENTER)
        box.append(sub)

        status_lbl = Gtk.Label(label=status)
        status_lbl.add_css_class("caption")
        status_lbl.add_css_class("dim-label")
        box.append(status_lbl)

        done_btn = Gtk.Button(label="Start using AgentOS")
        done_btn.add_css_class("suggested-action")
        done_btn.add_css_class("pill")
        done_btn.set_halign(Gtk.Align.CENTER)
        done_btn.connect("clicked", lambda *_: wizard.close())
        box.append(done_btn)

        toolbar.set_content(box)
        self.set_child(toolbar)


# ---------------------------------------------------------------------------
# Wizard window + application
# ---------------------------------------------------------------------------

class WizardWindow(Adw.ApplicationWindow):
    def __init__(self, app: "OnboardingApp") -> None:
        super().__init__(application=app)
        self.set_title("AgentOS Setup")
        self.set_default_size(640, 560)

        self.state = WizardState()
        self.nav_view = Adw.NavigationView()
        self.nav_view.push(WelcomePage(self))
        self.set_content(self.nav_view)

    def push(self, page: Adw.NavigationPage) -> None:
        self.nav_view.push(page)


class OnboardingApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="dev.agentos.Onboarding")
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        win = WizardWindow(self)
        win.present()


def main() -> None:
    app = OnboardingApp()
    app.run()


if __name__ == "__main__":
    main()
