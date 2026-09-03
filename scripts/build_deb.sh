#!/bin/sh
set -eu

root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
version="${AGENTOS_VERSION:-0.3.0}"
# Use a temp dir for staging so the build works on read-only or restricted mounts.
buildtmp="$(mktemp -d)"
trap 'rm -rf "$buildtmp"' EXIT
stage="$buildtmp/agentos-runtime"
out="$root/dist"

mkdir -p "$stage/DEBIAN" "$stage/usr/lib/agentos" "$stage/etc/agentos"
mkdir -p "$stage/lib/systemd/system" "$stage/usr/lib/systemd/user" "$stage/usr/bin" "$stage/var/lib/agentos"
mkdir -p "$stage/usr/lib/sysusers.d"
mkdir -p "$stage/usr/lib/tmpfiles.d"
mkdir -p "$stage/usr/lib/agentos/agents"
mkdir -p "$stage/etc/xdg/autostart"

# Copy Python source, packaging helpers, scripts, DB migrations, and agents.
cp -R "$root/agentos" "$root/cmd" "$root/db" "$root/packaging" "$root/scripts" \
  "$stage/usr/lib/agentos/"
cp -R "$root/agents" "$stage/usr/lib/agentos/"
# Strip compiled bytecode — it will be regenerated on the target system.
find "$stage/usr/lib/agentos" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Default config files (mode 640 owner root:agentos set in postinst).
cp "$root/config/agentos.env" "$stage/etc/agentos/agentos.env"
cp "$root/config/config.json" "$root/config/providers.json" "$stage/etc/agentos/"

# System-level units go in /lib/systemd/system for widest distro compatibility.
cp "$root/packaging/systemd/agentos-runtime.service" \
   "$root/packaging/systemd/agentos-firstboot.service" \
   "$root/packaging/systemd/agentos-helper.service" \
   "$root/packaging/systemd/agentos-assistant.service" \
   "$root/packaging/systemd/agentos-shell-agent.service" \
   "$root/packaging/systemd/agentos-file-agent.service" \
   "$root/packaging/systemd/agentos-system-agent.service" \
   "$stage/lib/systemd/system/"

# Desktop units target graphical-session.target, which only exists in the
# systemd --user instance — install as user units, enabled globally below.
cp "$root/packaging/systemd/agentos-shell.service" \
   "$root/packaging/systemd/agentos-launcher.service" \
   "$stage/usr/lib/systemd/user/"

# sysusers.d and tmpfiles.d for declarative user/dir provisioning.
cp "$root/packaging/sysusers/agentos.conf" "$stage/usr/lib/sysusers.d/agentos.conf"
cp "$root/packaging/tmpfiles/agentos.conf"  "$stage/usr/lib/tmpfiles.d/agentos.conf"

# /usr/bin/agentosd shim — thin launcher so PATH-based invocation works.
cat > "$stage/usr/bin/agentosd" <<'SHIM'
#!/bin/sh
cd /usr/lib/agentos
exec /usr/bin/python3 -m cmd.agentosd "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentosd"

# /usr/bin/agentos-onboarding convenience symlink target.
cat > "$stage/usr/bin/agentos-onboarding" <<'SHIM'
#!/bin/sh
exec /usr/lib/agentos/packaging/firstboot/agentos-onboarding "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentos-onboarding"

# /usr/bin/agentos-shell launcher.
cat > "$stage/usr/bin/agentos-shell" <<'SHIM'
#!/bin/sh
cd /usr/lib/agentos
exec /usr/bin/python3 -m agentos.shell.main "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentos-shell"

# /usr/bin/agentos-launcher — NLP chat bar launcher.
cat > "$stage/usr/bin/agentos-launcher" <<'SHIM'
#!/bin/sh
cd /usr/lib/agentos
exec /usr/bin/python3 -m agentos.shell.launcher "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentos-launcher"

# /usr/bin/agentos-onboarding-gui convenience symlink target.
cat > "$stage/usr/bin/agentos-onboarding-gui" <<'SHIM'
#!/bin/sh
exec /usr/lib/agentos/packaging/firstboot/agentos-onboarding-gui "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentos-onboarding-gui"

# /usr/bin/agentosd-helper launcher.
cat > "$stage/usr/bin/agentosd-helper" <<'SHIM'
#!/bin/sh
cd /usr/lib/agentos
exec /usr/bin/python3 -m agentos.helper.main "$@"
SHIM
chmod 0755 "$stage/usr/bin/agentosd-helper"

# Make all shell scripts executable.
chmod 0755 \
  "$stage/usr/lib/agentos/scripts/"*.sh \
  "$stage/usr/lib/agentos/packaging/firstboot/agentos-onboarding" \
  "$stage/usr/lib/agentos/packaging/firstboot/agentos-onboarding-gui" \
  "$stage/usr/lib/agentos/packaging/firstboot/prepare-firstboot.sh" \
  "$stage/usr/lib/agentos/packaging/iso/install-agentos.sh" \
  "$stage/usr/lib/agentos/packaging/launcher/setup-keybinding.sh"

# Autostart: register the Super+Space launcher shortcut on first login.
install -m 0644 "$root/packaging/launcher/agentos-launcher-keybind.desktop" \
  "$stage/etc/xdg/autostart/agentos-launcher-keybind.desktop"

# Make agent scripts executable.
find "$stage/usr/lib/agentos/agents" -name "*.py" -exec chmod 0755 {} +

# ------------------------------------------------------------------ DEBIAN/control

cat > "$stage/DEBIAN/control" <<EOF
Package: agentos-runtime
Version: $version
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), systemd, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1
Recommends: gnome-terminal
Maintainer: AgentOS contributors
Description: AgentOS control plane, desktop shell, and vendor-neutral LLM gateway
 Policy-controlled agent runtime, audit service, local inference gateway,
 GTK4 desktop shell, privileged helper daemon, and bundled agents.
 Includes an OpenAI-compatible /v1/chat/completions endpoint that routes to any
 cloud or local LLM provider (OpenAI, Anthropic, Gemini, Grok, OpenRouter,
 DeepSeek, Mistral, Groq, Together, Fireworks, Cerebras, Moonshot, Z.AI,
 MiniMax, Alibaba Qwen, Nous, Ollama, vLLM, LM Studio, or any custom
 OpenAI-compatible base URL).
EOF

# ------------------------------------------------------------------ DEBIAN/postinst

cat > "$stage/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

# Create system user/group if not present (sysusers.d handles this on
# modern systemd, but some installers don't run it automatically).
if ! getent group agentos >/dev/null 2>&1; then
    addgroup --system agentos
fi
if ! getent passwd agentos >/dev/null 2>&1; then
    adduser --system --ingroup agentos \
        --home /var/lib/agentos --no-create-home \
        --shell /usr/sbin/nologin \
        --gecos "AgentOS runtime" \
        agentos
fi

# State directory owned by the daemon user.
install -d -o agentos -g agentos -m 0700 /var/lib/agentos

# Runtime socket directory.
install -d -o root -g agentos -m 0775 /run/agentos

# Config directory: root owns, agentos group may read.
chown root:agentos \
    /etc/agentos/agentos.env \
    /etc/agentos/config.json \
    /etc/agentos/providers.json
chmod 0640 \
    /etc/agentos/agentos.env \
    /etc/agentos/config.json \
    /etc/agentos/providers.json

# secrets.json may not exist yet (created by onboarding wizard).
if [ -f /etc/agentos/secrets.json ]; then
    chown root:root /etc/agentos/secrets.json
    chmod 0600 /etc/agentos/secrets.json
fi

# Agent install directory.
install -d -o root -g agentos -m 0755 /usr/lib/agentos/agents

# Initialise the SQLite database if it does not already exist.
if [ ! -f /var/lib/agentos/agentos.db ]; then
    cd /usr/lib/agentos && /usr/bin/python3 scripts/init_db.py || true
fi

systemctl daemon-reload || true

# Enable and start core services.
systemctl enable agentos-runtime.service agentos-firstboot.service \
    agentos-helper.service || true

# Enable bundled agent services.
systemctl enable \
    agentos-assistant.service \
    agentos-shell-agent.service \
    agentos-file-agent.service \
    agentos-system-agent.service || true

# Enable the desktop shell + NLP launcher as user units for every account
# (graphical-session.target only exists in the systemd --user instance).
systemctl --global enable agentos-shell.service agentos-launcher.service || true

# Start runtime + helper now (agents start via dependencies).
systemctl start agentos-runtime.service agentos-helper.service 2>/dev/null || true
EOF
chmod 0755 "$stage/DEBIAN/postinst"

# ------------------------------------------------------------------ DEBIAN/prerm

cat > "$stage/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    for svc in agentos-assistant agentos-shell-agent agentos-file-agent \
               agentos-system-agent agentos-helper agentos-runtime agentos-firstboot; do
        systemctl stop "${svc}.service" 2>/dev/null || true
        systemctl disable "${svc}.service" 2>/dev/null || true
    done
    systemctl --global disable agentos-shell.service agentos-launcher.service 2>/dev/null || true
fi
EOF
chmod 0755 "$stage/DEBIAN/prerm"

# ------------------------------------------------------------------ DEBIAN/postrm

cat > "$stage/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "purge" ]; then
    rm -rf /etc/agentos /var/lib/agentos /run/agentos
    userdel agentos 2>/dev/null || true
    groupdel agentos 2>/dev/null || true
fi
EOF
chmod 0755 "$stage/DEBIAN/postrm"

# ------------------------------------------------------------------ Build the .deb (ar archive)

mkdir -p "$out"
(
  cd "$stage"
  printf '2.0\n' > "$buildtmp/debian-binary"
  tar -czf "$buildtmp/control.tar.gz" -C DEBIAN .
  tar -czf "$buildtmp/data.tar.gz" --exclude=DEBIAN .
)
# make_ar.py uses write_bytes() and overwrites in-place — no pre-removal needed.
python3 "$root/scripts/make_ar.py" "$out/agentos-runtime_${version}_all.deb" \
  "$buildtmp/debian-binary" \
  "$buildtmp/control.tar.gz" \
  "$buildtmp/data.tar.gz"
printf '%s\n' "$out/agentos-runtime_${version}_all.deb"
