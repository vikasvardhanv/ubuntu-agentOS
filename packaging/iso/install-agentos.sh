#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$arch" in
  arm64|aarch64) ;;
  *) printf 'WARNING: AgentOS is built for arm64; this system reports "%s".\n' "$arch" >&2 ;;
esac

package="/cdrom/agentos/agentos-runtime.deb"
if [ ! -f "$package" ]; then
  package="$(CDPATH= cd -- "$(dirname "$0")" && pwd)/agentos-runtime.deb"
fi

if [ ! -f "$package" ]; then
  printf 'ERROR: agentos-runtime.deb not found next to this script or in /cdrom/agentos.\n' >&2
  exit 1
fi

printf 'Installing AgentOS runtime…\n'
if ! dpkg -i "$package"; then
  printf 'Resolving missing dependencies…\n'
  apt-get update -qq || true
  apt-get install -f -y
fi

systemctl daemon-reload
systemctl enable agentos-runtime.service agentos-firstboot.service

printf '\nAgentOS installed.\n'
printf 'Reboot to begin first-boot setup (name + connect an AI agent).\n'
