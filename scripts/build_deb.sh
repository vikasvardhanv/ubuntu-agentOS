#!/bin/sh
set -eu

root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
version="${AGENTOS_VERSION:-0.2.0}"
stage="$root/build/deb/agentos-runtime"
out="$root/dist"

rm -rf "$stage"
mkdir -p "$stage/DEBIAN" "$stage/usr/lib/agentos" "$stage/etc/agentos"
mkdir -p "$stage/lib/systemd/system" "$stage/usr/bin" "$stage/var/lib/agentos"
mkdir -p "$stage/usr/lib/sysusers.d"
mkdir -p "$stage/usr/lib/tmpfiles.d"

cp -R "$root/agentos" "$root/cmd" "$root/db" "$root/packaging" "$root/scripts" \
  "$stage/usr/lib/agentos/"
find "$stage/usr/lib/agentos" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$root/config/agentos.env" "$stage/etc/agentos/agentos.env"
cp "$root/config/config.json" "$root/config/providers.json" "$stage/etc/agentos/"
cp "$root/packaging/systemd/agentos-runtime.service" \
  "$root/packaging/systemd/agentos-firstboot.service" "$stage/lib/systemd/system/"
cp "$root/packaging/sysusers/agentos.conf" "$stage/usr/lib/sysusers.d/agentos.conf"
cp "$root/packaging/tmpfiles/agentos.conf" "$stage/usr/lib/tmpfiles.d/agentos.conf"

cat > "$stage/usr/bin/agentosd" <<'EOF'
#!/bin/sh
cd /usr/lib/agentos
exec /usr/bin/python3 -m cmd.agentosd "$@"
EOF
chmod 0755 "$stage/usr/bin/agentosd"
chmod 0755 "$stage/usr/lib/agentos/scripts/"*.sh \
  "$stage/usr/lib/agentos/packaging/firstboot/agentos-onboarding"

cat > "$stage/DEBIAN/control" <<EOF
Package: agentos-runtime
Version: $version
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), systemd
Maintainer: AgentOS contributors
Description: AgentOS control plane and vendor-neutral LLM gateway
 Policy-controlled agent runtime, audit service, and local inference gateway.
EOF

cat > "$stage/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if ! getent group agentos >/dev/null; then addgroup --system agentos; fi
if ! getent passwd agentos >/dev/null; then
  adduser --system --ingroup agentos --home /var/lib/agentos --no-create-home agentos
fi
install -d -o agentos -g agentos -m 0700 /var/lib/agentos
chown root:agentos /etc/agentos/agentos.env /etc/agentos/config.json /etc/agentos/providers.json
chmod 0640 /etc/agentos/agentos.env /etc/agentos/config.json /etc/agentos/providers.json
systemctl daemon-reload || true
systemctl enable agentos-runtime.service agentos-firstboot.service || true
EOF
chmod 0755 "$stage/DEBIAN/postinst"

mkdir -p "$out"
(
  cd "$stage"
  printf '2.0\n' > "$root/build/deb/debian-binary"
  tar -czf "$root/build/deb/control.tar.gz" -C DEBIAN .
  tar -czf "$root/build/deb/data.tar.gz" --exclude=DEBIAN .
)
rm -f "$out/agentos-runtime_${version}_all.deb"
python3 "$root/scripts/make_ar.py" "$out/agentos-runtime_${version}_all.deb" \
  "$root/build/deb/debian-binary" "$root/build/deb/control.tar.gz" "$root/build/deb/data.tar.gz"
printf '%s\n' "$out/agentos-runtime_${version}_all.deb"
