#!/bin/sh
set -eu

install -d -m 0700 /var/lib/agentos
install -d -m 0755 /etc/xdg/autostart
install -m 0644 /usr/lib/agentos/packaging/firstboot/agentos-onboarding.desktop \
  /etc/xdg/autostart/agentos-onboarding.desktop
