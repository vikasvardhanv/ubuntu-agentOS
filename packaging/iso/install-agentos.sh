#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

package="/cdrom/agentos/agentos-runtime.deb"
if [ ! -f "$package" ]; then
  package="$(dirname "$0")/agentos-runtime.deb"
fi

dpkg -i "$package"
systemctl enable agentos-runtime.service agentos-firstboot.service
printf 'AgentOS installed. Reboot to begin first-boot setup.\n'
