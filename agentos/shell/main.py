#!/usr/bin/env python3
"""AgentOS Desktop Shell — GTK4 + libadwaita control panel.

Panels (sidebar):
  • Chat      — conversational UI → POST /v1/chat/completions
  • Agents    — list + install agents
  • Tasks     — recent task status
  • Approvals — pending human-approval queue (polls every 3 s)
  • Audit     — last 50 audit events
  • Settings  — provider / model info + re-run onboarding
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

DAEMON_API = os.environ.get("AGENTOS_API", "http://127.0.0.1:7788")
API_TOKEN = os.environ.get("AGENTOS_API_TOKEN", "")
POLL_INTERVAL_MS = 3000  # ms — approval poll cadence


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    if extra:
        h.update(extra)
    return h


def _api_get(path: str) -> Any:
    req = urllib.request.Request(f"{DAEMON_API}{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


def _api_post(path: str, body: dict[str, Any]) -> Any:
    data = json.dumps(body).encode()
    h = _headers({"Content-Length": str(len(data))})
    req = urllib.request.Request(f"{DAEMON_API}{path}", data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _api_safe(fn, *args, **kwargs) -> tuple[Any, str]:
    """Call fn(*args, **kwargs); return (result, "") or (None, error_str)."""
    try:
        return fn(*args, **kwargs), ""
    except urllib.error.URLError as exc:
        return None, f"Connection error: {exc.reason}"
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Chat Panel
# ---------------------------------------------------------------------------

class ChatPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._history: list[dict[str, str]] = []

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._msg_box.set_margin_start(12)
        self._msg_box.set_margin_end(12)
        self._msg_box.set_margin_top(12)
        self._msg_box.set_margin_bottom(12)
        scroll.set_child(self._msg_box)
        self.append(scroll)

        # Input row
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_row.set_margin_start(12)
        input_row.set_margin_end(12)
        input_row.set_margin_top(8)
        input_row.set_margin_bottom(12)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text("Ask AgentOS anything…")
        self._entry.connect("activate", self._on_send)
        input_row.append(self._entry)

        send_btn = Gtk.Button(label="Send")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_send)
        input_row.append(send_btn)

        self.append(input_row)

    def _add_bubble(self, role: str, text: str) -> None:
        bubble = Gtk.Label(label=text)
        bubble.set_wrap(True)
        bubble.set_wrap_mode(2)  # WORD_CHAR
        bubble.set_xalign(0)
        bubble.set_selectable(True)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        if role == "user":
            bubble.add_css_class("message-user")
            row.set_halign(Gtk.Align.END)
        else:
            bubble.add_css_class("message-assistant")
            row.set_halign(Gtk.Align.START)
        row.append(bubble)
        self._msg_box.append(row)

    def _on_send(self, *_args: Any) -> None:
        text = self._entry.get_text().strip()
        if not text:
            return
        self._entry.set_text("")
        self._add_bubble("user", text)
        self._history.append({"role": "user", "content": text})

        thinking = Gtk.Label(label="…")
        thinking.add_css_class("message-assistant")
        row = Gtk.Box()
        row.set_halign(Gtk.Align.START)
        row.append(thinking)
        self._msg_box.append(row)

        history_snapshot = list(self._history)

        def _bg() -> None:
            result, error = _api_safe(
                _api_post,
                "/v1/chat/completions",
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are AgentOS Assistant, an AI agent running on the "
                                "user's Ubuntu desktop. Be helpful and concise."
                            ),
                        },
                        *history_snapshot,
                    ]
                },
            )

            def _update() -> None:
                self._msg_box.remove(row)
                if error:
                    reply = f"[Error: {error}]"
                else:
                    try:
                        reply = result["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        reply = str(result)
                self._history.append({"role": "assistant", "content": reply})
                self._add_bubble("assistant", reply)
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()


# ---------------------------------------------------------------------------
# Agents Panel
# ---------------------------------------------------------------------------

class AgentsPanel(Gtk.Box):
    def __init__(self, app: "AgentOSShell") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._app = app

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(12)
        toolbar.set_margin_bottom(8)

        title = Gtk.Label(label="Registered Agents")
        title.set_hexpand(True)
        title.set_xalign(0)
        title.add_css_class("title-4")
        toolbar.append(title)

        refresh_btn = Gtk.Button(label="↺ Refresh")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        toolbar.append(refresh_btn)

        install_btn = Gtk.Button(label="+ Install")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._open_marketplace)
        toolbar.append(install_btn)

        self.append(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        scroll.set_child(self._list_box)
        self.append(scroll)

        self.refresh()

    def refresh(self) -> None:
        while row := self._list_box.get_first_child():
            self._list_box.remove(row)

        def _bg() -> None:
            result, error = _api_safe(_api_get, "/v1/agents")
            agents = result if isinstance(result, list) else (result or {}).get("data", []) if result else []

            def _update() -> None:
                if error:
                    lbl = Gtk.Label(label=f"Error: {error}")
                    row = Gtk.ListBoxRow()
                    row.set_child(lbl)
                    self._list_box.append(row)
                    return
                for agent in agents:
                    row = Gtk.ListBoxRow()
                    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    box.set_margin_start(12)
                    box.set_margin_end(12)
                    box.set_margin_top(8)
                    box.set_margin_bottom(8)

                    name_lbl = Gtk.Label(label=agent.get("name", "?"))
                    name_lbl.set_hexpand(True)
                    name_lbl.set_xalign(0)
                    name_lbl.add_css_class("heading")
                    box.append(name_lbl)

                    trust = agent.get("trust_level", "user")
                    trust_lbl = Gtk.Label(label=trust)
                    trust_lbl.add_css_class("caption")
                    box.append(trust_lbl)

                    state = agent.get("state", "")
                    state_lbl = Gtk.Label(label=state)
                    if state == "registered":
                        state_lbl.add_css_class("success")
                    box.append(state_lbl)

                    row.set_child(box)
                    self._list_box.append(row)
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()

    def _open_marketplace(self, *_: Any) -> None:
        dlg = MarketplaceDialog(self._app.get_active_window())
        dlg.present()


class MarketplaceDialog(Adw.Dialog):
    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__()
        self.set_title("Agent Marketplace")
        self.set_content_width(480)
        self.set_content_height(400)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        box.append(header)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        self._list_box.set_margin_top(12)
        self._list_box.set_margin_bottom(12)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._list_box)
        box.append(scroll)

        self.set_child(box)
        self._load()

    def _load(self) -> None:
        def _bg() -> None:
            result, error = _api_safe(_api_get, "/v1/marketplace/agents")
            agents = (result or {}).get("data", []) if result else []

            def _update() -> None:
                if error:
                    lbl = Gtk.Label(label=f"Error: {error}")
                    row = Gtk.ListBoxRow()
                    row.set_child(lbl)
                    self._list_box.append(row)
                    return
                for agent in agents:
                    row = Gtk.ListBoxRow()
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    box.set_margin_start(12)
                    box.set_margin_end(12)
                    box.set_margin_top(8)
                    box.set_margin_bottom(8)

                    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                    name_lbl = Gtk.Label(label=agent.get("name", "?"))
                    name_lbl.set_hexpand(True)
                    name_lbl.set_xalign(0)
                    name_lbl.add_css_class("heading")
                    top.append(name_lbl)

                    install_btn = Gtk.Button(label="Install")
                    install_btn.add_css_class("suggested-action")
                    _name = agent.get("name", "")
                    install_btn.connect("clicked", lambda _, n=_name: self._install(n))
                    top.append(install_btn)
                    box.append(top)

                    desc_lbl = Gtk.Label(label=agent.get("description", ""))
                    desc_lbl.set_wrap(True)
                    desc_lbl.set_xalign(0)
                    desc_lbl.add_css_class("caption")
                    box.append(desc_lbl)

                    row.set_child(box)
                    self._list_box.append(row)
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()

    def _install(self, name: str) -> None:
        def _bg() -> None:
            result, error = _api_safe(_api_post, f"/v1/marketplace/agents/{name}/install", {})

            def _update() -> None:
                msg = f"Installed {name}" if not error else f"Error: {error}"
                toast = Adw.Toast(title=msg)
                # Toast needs an overlay; skip if not available.
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()


# ---------------------------------------------------------------------------
# Tasks Panel
# ---------------------------------------------------------------------------

class TasksPanel(Gtk.Box):
    _STATE_CSS = {
        "pending": "warning",
        "running": "accent",
        "completed": "success",
        "failed": "error",
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(12)
        toolbar.set_margin_bottom(8)

        title = Gtk.Label(label="Recent Tasks")
        title.set_hexpand(True)
        title.set_xalign(0)
        title.add_css_class("title-4")
        toolbar.append(title)

        refresh_btn = Gtk.Button(label="↺ Refresh")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        toolbar.append(refresh_btn)

        self.append(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        scroll.set_child(self._list_box)
        self.append(scroll)

        self.refresh()

    def refresh(self) -> None:
        while row := self._list_box.get_first_child():
            self._list_box.remove(row)

        def _bg() -> None:
            # Collect tasks from all agents.
            agents_result, _ = _api_safe(_api_get, "/v1/agents")
            agents = agents_result if isinstance(agents_result, list) else \
                     (agents_result or {}).get("data", []) if agents_result else []
            all_tasks: list[dict[str, Any]] = []
            for agent in agents:
                aid = agent.get("id", "")
                tasks_result, _ = _api_safe(_api_get, f"/v1/agents/{aid}/tasks")
                if tasks_result:
                    t = tasks_result if isinstance(tasks_result, list) else \
                        tasks_result.get("data", [])
                    all_tasks.extend(t)
            all_tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            all_tasks = all_tasks[:50]

            def _update() -> None:
                for task in all_tasks:
                    row = Gtk.ListBoxRow()
                    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    box.set_margin_start(12)
                    box.set_margin_end(12)
                    box.set_margin_top(6)
                    box.set_margin_bottom(6)

                    id_lbl = Gtk.Label(label=task.get("id", "?")[:8] + "…")
                    id_lbl.set_xalign(0)
                    id_lbl.add_css_class("monospace")
                    id_lbl.add_css_class("caption")
                    box.append(id_lbl)

                    agent_lbl = Gtk.Label(label=task.get("agent_id", "?")[:8] + "…")
                    agent_lbl.set_xalign(0)
                    agent_lbl.set_hexpand(True)
                    agent_lbl.add_css_class("caption")
                    box.append(agent_lbl)

                    state = task.get("state", "?")
                    state_lbl = Gtk.Label(label=state)
                    css = self._STATE_CSS.get(state, "")
                    if css:
                        state_lbl.add_css_class(css)
                    box.append(state_lbl)

                    row.set_child(box)
                    self._list_box.append(row)
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()


# ---------------------------------------------------------------------------
# Approvals Panel
# ---------------------------------------------------------------------------

class ApprovalsPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(12)
        toolbar.set_margin_bottom(8)

        title = Gtk.Label(label="Pending Approvals")
        title.set_hexpand(True)
        title.set_xalign(0)
        title.add_css_class("title-4")
        toolbar.append(title)

        self._badge = Gtk.Label(label="0")
        self._badge.add_css_class("badge")
        toolbar.append(self._badge)

        self.append(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        scroll.set_child(self._list_box)
        self.append(scroll)

        # Start polling every 3 seconds.
        GLib.timeout_add(POLL_INTERVAL_MS, self._poll)
        self._poll()

    def _poll(self) -> bool:
        def _bg() -> None:
            result, _ = _api_safe(_api_get, "/v1/approvals/pending")
            approvals = result if isinstance(result, list) else \
                        (result or {}).get("data", []) if result else []
            GLib.idle_add(self._refresh_ui, approvals)

        threading.Thread(target=_bg, daemon=True).start()
        return True  # repeat

    def _refresh_ui(self, approvals: list[dict[str, Any]]) -> bool:
        while row := self._list_box.get_first_child():
            self._list_box.remove(row)

        self._badge.set_label(str(len(approvals)))

        if not approvals:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="No pending approvals")
            lbl.set_margin_top(24)
            lbl.set_margin_bottom(24)
            lbl.add_css_class("dim-label")
            row.set_child(lbl)
            self._list_box.append(row)
            return False

        for approval in approvals:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_margin_top(10)
            box.set_margin_bottom(10)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            action_lbl = Gtk.Label(
                label=f"{approval.get('action', '?')} on {approval.get('resource', '?') or '(none)'}"
            )
            action_lbl.set_hexpand(True)
            action_lbl.set_xalign(0)
            action_lbl.add_css_class("heading")
            top.append(action_lbl)
            box.append(top)

            agent_lbl = Gtk.Label(label=f"Agent: {approval.get('agent_id', '?')[:16]}…")
            agent_lbl.set_xalign(0)
            agent_lbl.add_css_class("caption")
            box.append(agent_lbl)

            btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            btn_row.set_halign(Gtk.Align.END)

            aid = approval.get("id", "")

            deny_btn = Gtk.Button(label="Deny")
            deny_btn.add_css_class("destructive-action")
            deny_btn.connect("clicked", lambda _, a=aid: self._decide(a, False))
            btn_row.append(deny_btn)

            approve_btn = Gtk.Button(label="Approve")
            approve_btn.add_css_class("suggested-action")
            approve_btn.connect("clicked", lambda _, a=aid: self._decide(a, True))
            btn_row.append(approve_btn)

            box.append(btn_row)
            row.set_child(box)
            self._list_box.append(row)

        return False

    def _decide(self, approval_id: str, approved: bool) -> None:
        def _bg() -> None:
            _api_safe(
                _api_post,
                f"/v1/approvals/{approval_id}/decision",
                {"approved": approved, "reason": "user decision via shell"},
            )
            GLib.idle_add(self._poll)

        threading.Thread(target=_bg, daemon=True).start()


# ---------------------------------------------------------------------------
# Audit Panel
# ---------------------------------------------------------------------------

class AuditPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(12)
        toolbar.set_margin_bottom(8)

        title = Gtk.Label(label="Audit Log")
        title.set_hexpand(True)
        title.set_xalign(0)
        title.add_css_class("title-4")
        toolbar.append(title)

        refresh_btn = Gtk.Button(label="↺ Refresh")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        toolbar.append(refresh_btn)

        self.append(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        scroll.set_child(self._list_box)
        self.append(scroll)

        self.refresh()

    def refresh(self) -> None:
        while row := self._list_box.get_first_child():
            self._list_box.remove(row)

        def _bg() -> None:
            result, error = _api_safe(_api_get, "/v1/audit?limit=50")
            events = (result or {}).get("data", []) if result else []

            def _update() -> None:
                if error:
                    lbl = Gtk.Label(label=f"Error: {error}")
                    r = Gtk.ListBoxRow()
                    r.set_child(lbl)
                    self._list_box.append(r)
                    return
                for evt in events:
                    row = Gtk.ListBoxRow()
                    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    box.set_margin_start(12)
                    box.set_margin_end(12)
                    box.set_margin_top(6)
                    box.set_margin_bottom(6)

                    ts = str(evt.get("occurred_at", ""))[:19]
                    ts_lbl = Gtk.Label(label=ts)
                    ts_lbl.add_css_class("monospace")
                    ts_lbl.add_css_class("caption")
                    box.append(ts_lbl)

                    type_lbl = Gtk.Label(label=evt.get("event_type", "?"))
                    type_lbl.set_hexpand(True)
                    type_lbl.set_xalign(0)
                    box.append(type_lbl)

                    actor_lbl = Gtk.Label(label=evt.get("actor_id", "?"))
                    actor_lbl.add_css_class("dim-label")
                    actor_lbl.add_css_class("caption")
                    box.append(actor_lbl)

                    row.set_child(box)
                    self._list_box.append(row)
                return False

            GLib.idle_add(_update)

        threading.Thread(target=_bg, daemon=True).start()


# ---------------------------------------------------------------------------
# Settings Panel
# ---------------------------------------------------------------------------

class SettingsPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(24)
        self.set_margin_bottom(24)

        title = Gtk.Label(label="Settings")
        title.set_xalign(0)
        title.add_css_class("title-2")
        self.append(title)

        # Provider info group
        provider_group = Adw.PreferencesGroup(title="LLM Provider")
        self.append(provider_group)

        self._provider_row = Adw.ActionRow(title="Provider", subtitle="Loading…")
        provider_group.add(self._provider_row)

        self._model_row = Adw.ActionRow(title="Model", subtitle="Loading…")
        provider_group.add(self._model_row)

        # Daemon connectivity
        daemon_group = Adw.PreferencesGroup(title="Daemon")
        self.append(daemon_group)

        self._daemon_row = Adw.ActionRow(title="API endpoint", subtitle=DAEMON_API)
        daemon_group.add(self._daemon_row)

        # Actions
        actions_group = Adw.PreferencesGroup(title="Actions")
        self.append(actions_group)

        onboarding_row = Adw.ActionRow(title="Re-run onboarding wizard")
        onboarding_btn = Gtk.Button(label="Launch")
        onboarding_btn.set_valign(Gtk.Align.CENTER)
        onboarding_btn.connect("clicked", self._launch_onboarding)
        onboarding_row.add_suffix(onboarding_btn)
        onboarding_row.set_activatable_widget(onboarding_btn)
        actions_group.add(onboarding_row)

        self._load_provider()

    def _load_provider(self) -> None:
        providers_path = "/etc/agentos/providers.json"
        try:
            import json as _json
            data = _json.loads(open(providers_path).read())
            selected = data.get("selected", "")
            providers = data.get("providers", {})
            if selected and selected in providers:
                p = providers[selected]
                self._provider_row.set_subtitle(selected)
                self._model_row.set_subtitle(str(p.get("model", "—")))
            else:
                self._provider_row.set_subtitle(selected or "Not configured")
                self._model_row.set_subtitle("—")
        except Exception as exc:
            self._provider_row.set_subtitle(f"Error: {exc}")

    def _launch_onboarding(self, *_: Any) -> None:
        try:
            subprocess.Popen(["agentos-onboarding-gui"])
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class MainWindow(Adw.ApplicationWindow):
    _PAGES = [
        ("chat-symbolic", "Chat", "chat"),
        ("system-run-symbolic", "Agents", "agents"),
        ("view-list-symbolic", "Tasks", "tasks"),
        ("dialog-question-symbolic", "Approvals", "approvals"),
        ("text-x-generic-symbolic", "Audit", "audit"),
        ("preferences-system-symbolic", "Settings", "settings"),
    ]

    def __init__(self, app: "AgentOSShell") -> None:
        super().__init__(application=app)
        self.set_default_size(1100, 720)
        self.set_title("AgentOS")

        # Root layout: navigation split view
        split_view = Adw.NavigationSplitView()
        split_view.set_min_sidebar_width(200)
        split_view.set_max_sidebar_width(240)

        # Sidebar
        sidebar_page = Adw.NavigationPage(title="AgentOS")
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        sidebar_box.append(header)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("navigation-sidebar")
        self._list_box.connect("row-selected", self._on_nav_selected)

        for icon, label, _key in self._PAGES:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            img = Gtk.Image.new_from_icon_name(icon)
            box.append(img)
            lbl = Gtk.Label(label=label)
            lbl.set_xalign(0)
            box.append(lbl)
            row.set_child(box)
            self._list_box.append(row)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._list_box)
        sidebar_box.append(scroll)

        sidebar_page.set_child(sidebar_box)
        split_view.set_sidebar(sidebar_page)

        # Content area: stack of panels
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._panels: dict[str, Gtk.Widget] = {
            "chat": ChatPanel(),
            "agents": AgentsPanel(app),
            "tasks": TasksPanel(),
            "approvals": ApprovalsPanel(),
            "audit": AuditPanel(),
            "settings": SettingsPanel(),
        }
        for key, panel in self._panels.items():
            self._stack.add_named(panel, key)

        content_page = Adw.NavigationPage(title="AgentOS")
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_header = Adw.HeaderBar()
        content_box.append(content_header)
        content_box.append(self._stack)
        content_page.set_child(content_box)
        split_view.set_content(content_page)

        self.set_content(split_view)

        # Select first row.
        first = self._list_box.get_row_at_index(0)
        if first:
            self._list_box.select_row(first)

    def _on_nav_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        idx = row.get_index()
        if 0 <= idx < len(self._PAGES):
            _icon, _label, key = self._PAGES[idx]
            self._stack.set_visible_child_name(key)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class AgentOSShell(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="dev.agentos.Shell")
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        win = MainWindow(self)
        win.present()


def main() -> None:
    app = AgentOSShell()
    app.run()


if __name__ == "__main__":
    main()
