#!/bin/sh
# Registers the AgentOS launcher global shortcut (Super+Space) via GNOME
# custom keybindings. Idempotent, runs once per user via autostart.
set -eu

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/agentos"
MARKER="$STATE_DIR/launcher-keybind-done"
[ -f "$MARKER" ] && exit 0

SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
KEY="custom-keybindings"
BINDING_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/agentos-launcher/"

if command -v gsettings >/dev/null 2>&1; then
    current="$(gsettings get "$SCHEMA" "$KEY" 2>/dev/null || printf '@as []')"
    case "$current" in
        *"$BINDING_PATH"*) ;;  # already registered
        *)
            if [ "$current" = "@as []" ] || [ "$current" = "[]" ]; then
                new="['$BINDING_PATH']"
            else
                new="$(printf '%s' "$current" | sed "s/]\$/, '$BINDING_PATH']/")"
            fi
            gsettings set "$SCHEMA" "$KEY" "$new"
            ;;
    esac

    custom_schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BINDING_PATH"
    gsettings set "$custom_schema" name "AgentOS Launcher"
    gsettings set "$custom_schema" command "agentos-launcher --toggle"
    gsettings set "$custom_schema" binding "<Super>space"
fi

mkdir -p "$STATE_DIR"
touch "$MARKER"
