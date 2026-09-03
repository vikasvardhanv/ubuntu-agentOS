#!/usr/bin/env python3
"""AgentOS Launcher — the NLP-first front door to the desktop.

A small, borderless, always-available chat bar. Type what you want
("organize my downloads folder", "install Spotify", "write an email to
my boss") and AgentOS agents do it via the existing
``/v1/chat/completions`` gateway + tool-calling agents.

Single-instance GApplication: a global keyboard shortcut runs
``agentos-launcher --toggle`` to show/hide the bar without spawning a
new process each time (see ``packaging/launcher`` for the autostart and
keybinding setup).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

DAEMON_API = os.environ.get("AGENTOS_API", "http://127.0.0.1:7788")
API_TOKEN = os.environ.get("AGENTOS_API_TOKEN", "")
PROFILE_FILE = Path("/etc/agentos/profile.json")

SYSTEM_PROMPT = (
    "You are AgentOS, an agent-first desktop assistant. The user typed a "
    "request into the always-on-top chat bar. Either answer directly, or "
    "call the appropriate tool/agent to get it done (organizing files, "
    "installing packages, drafting emails, system tasks, etc). Be concise."
)


def _user_name() -> str:
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        return str(data.get("name", "")).strip()
    except (OSError, ValueError):
        return ""


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    if extra:
        h.update(extra)
    return h


def _api_post(path: str, body: dict[str, Any]) -> Any:
    data = json.dumps(body).encode()
    h = _headers({"Content-Length": str(len(data))})
    req = urllib.request.Request(f"{DAEMON_API}{path}", data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


class LauncherWindow(Adw.Window):
    def __init__(self, app: "LauncherApp") -> None:
        super().__init__(application=app)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(680, 64)
        self.add_css_class("agentos-launcher")

        self._history: list[dict[str, str]] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("card")
        root.set_margin_start(2)
        root.set_margin_end(2)
        root.set_margin_top(2)
        root.set_margin_bottom(2)

        # Input row.
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_row.set_margin_start(14)
        input_row.set_margin_end(14)
        input_row.set_margin_top(12)
        input_row.set_margin_bottom(12)

        icon = Gtk.Image.new_from_icon_name("dev.agentos.Shell")
        icon.set_pixel_size(28)
        input_row.append(icon)

        name = _user_name()
        placeholder = f"What can I do for you, {name}?" if name else "Ask AgentOS anything, or tell it what to do…"

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.add_css_class("title-3")
        self._entry.set_placeholder_text(placeholder)
        self._entry.connect("activate", self._on_send)
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key)
        self._entry.add_controller(ctrl)
        input_row.append(self._entry)

        self._spinner = Gtk.Spinner()
        input_row.append(self._spinner)

        root.append(input_row)

        # Response area (collapsed until there's something to show).
        self._response_revealer = Gtk.Revealer()
        self._response_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

        scroll = Gtk.ScrolledWindow()
        scroll.set_max_content_height(360)
        scroll.set_propagate_natural_height(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._response_label = Gtk.Label()
        self._response_label.set_wrap(True)
        self._response_label.set_wrap_mode(2)  # WORD_CHAR
        self._response_label.set_xalign(0)
        self._response_label.set_selectable(True)
        self._response_label.set_margin_start(14)
        self._response_label.set_margin_end(14)
        self._response_label.set_margin_top(4)
        self._response_label.set_margin_bottom(12)

        scroll.set_child(self._response_label)
        self._response_revealer.set_child(scroll)
        root.append(self._response_revealer)

        self.set_content(root)

        # Position near the top-center of the primary display.
        self.connect("show", lambda *_: self._entry.grab_focus())

    # -- key handling --------------------------------------------------

    def _on_key(self, _ctrl: Gtk.EventControllerKey, keyval: int, *_args: Any) -> bool:
        if keyval == 65307:  # Escape
            self.hide_launcher()
            return True
        return False

    def hide_launcher(self) -> None:
        self._response_revealer.set_reveal_child(False)
        self._response_label.set_label("")
        self._entry.set_text("")
        self.hide()

    def toggle(self) -> None:
        if self.get_visible():
            self.hide_launcher()
        else:
            self.present()

    # -- send / receive --------------------------------------------------

    def _on_send(self, *_args: Any) -> None:
        text = self._entry.get_text().strip()
        if not text:
            return
        self._entry.set_sensitive(False)
        self._spinner.start()
        self._history.append({"role": "user", "content": text})
        history_snapshot = list(self._history)

        def _bg() -> None:
            try:
                result = _api_post(
                    "/v1/chat/completions",
                    {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history_snapshot]},
                )
                reply = result["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                try:
                    detail = json.loads(exc.read()).get("detail", "")
                except (OSError, ValueError, AttributeError):
                    detail = ""
                if "onboarding" in detail:
                    reply = (
                        "[AgentOS isn't connected to an AI agent yet. "
                        'Open Settings → "Re-run onboarding wizard" to connect one.]'
                    )
                else:
                    reply = f"[Error: {detail or exc.reason}]"
            except urllib.error.URLError as exc:
                reply = f"[AgentOS daemon unreachable: {exc.reason}]"
            except Exception as exc:  # noqa: BLE001 — surface any error to the bar
                reply = f"[Error: {exc}]"

            def _update() -> bool:
                self._history.append({"role": "assistant", "content": reply})
                self._response_label.set_label(reply)
                self._response_revealer.set_reveal_child(True)
                self._entry.set_text("")
                self._entry.set_sensitive(True)
                self._entry.grab_focus()
                self._spinner.stop()
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()


class LauncherApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="dev.agentos.Launcher",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.window: LauncherWindow | None = None
        self.add_main_option(
            "toggle", ord("t"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Toggle the launcher bar (show if hidden, hide if visible)", None,
        )
        self.add_main_option(
            "shell", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Open the full AgentOS desktop shell instead", None,
        )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.window = LauncherWindow(self)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict()
        assert self.window is not None
        if options.contains("shell"):
            try:
                subprocess.Popen(["agentos-shell"])
            except FileNotFoundError:
                pass
            return 0
        if options.contains("toggle"):
            self.window.toggle()
        else:
            self.window.present()
        self.hold()
        return 0

    def do_activate(self) -> None:
        assert self.window is not None
        self.window.present()


def main() -> None:
    app = LauncherApp()
    app.run()


if __name__ == "__main__":
    main()
