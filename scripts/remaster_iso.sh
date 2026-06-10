#!/bin/sh
set -eu

root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
source_iso="${1:-$root/ubuntu-26.04-desktop-arm64.iso}"
output_iso="${2:-$root/dist/agentos-26.04-desktop-arm64.iso}"
tree="$root/build/iso-tree"
overlay="$root/build/iso-overlay"
version="${AGENTOS_VERSION:-0.3.0}"
package="$root/dist/agentos-runtime_${version}_all.deb"

[ -f "$source_iso" ] || { echo "source ISO not found: $source_iso" >&2; exit 1; }
[ -f "$package" ] || "$root/scripts/build_deb.sh"

if [ -d "$tree" ]; then
  chmod -R u+w "$tree"
  rm -rf "$tree"
fi
rm -rf "$overlay"
mkdir -p "$tree" "$overlay" "$(dirname "$output_iso")"
bsdtar -xf "$source_iso" -C "$tree"
chmod -R u+w "$tree"

# Build AgentOS as an installer filesystem layer, preserving Ubuntu's base layers.
cp -R "$root/build/deb/agentos-runtime/"* "$overlay/"
rm -rf "$overlay/DEBIAN"
mkdir -p "$overlay/etc/systemd/system/multi-user.target.wants"
mkdir -p "$overlay/etc/systemd/system/graphical.target.wants"
ln -s /lib/systemd/system/agentos-runtime.service \
  "$overlay/etc/systemd/system/multi-user.target.wants/agentos-runtime.service"
ln -s /lib/systemd/system/agentos-firstboot.service \
  "$overlay/etc/systemd/system/graphical.target.wants/agentos-firstboot.service"
mksquashfs "$overlay" "$tree/casper/minimal.agentos.squashfs" \
  -quiet -no-recovery -no-xattrs -all-root -noappend
cp "$tree/casper/minimal.agentos.squashfs" \
  "$tree/casper/minimal.standard.agentos.squashfs"
overlay_size="$(du -sk "$overlay" | awk '{print $1 * 1024}')"
printf '%s\n' "$overlay_size" > "$tree/casper/minimal.agentos.size"
printf '%s\n' "$overlay_size" > "$tree/casper/minimal.standard.agentos.size"
cp "$tree/casper/minimal.manifest" "$tree/casper/minimal.agentos.manifest"
cp "$tree/casper/minimal.standard.manifest" "$tree/casper/minimal.standard.agentos.manifest"
printf 'agentos-runtime\t%s\n' "$version" >> "$tree/casper/minimal.agentos.manifest"
printf 'agentos-runtime\t%s\n' "$version" >> "$tree/casper/minimal.standard.agentos.manifest"
cp "$tree/casper/minimal.manifest.full" "$tree/casper/minimal.agentos.manifest.full"
cp "$tree/casper/minimal.standard.manifest.full" \
  "$tree/casper/minimal.standard.agentos.manifest.full"
printf 'agentos-runtime\t%s\n' "$version" >> "$tree/casper/minimal.agentos.manifest.full"
printf 'agentos-runtime\t%s\n' "$version" >> "$tree/casper/minimal.standard.agentos.manifest.full"
perl -pi -e 's/path: minimal\.squashfs/path: minimal.agentos.squashfs/' \
  "$tree/casper/install-sources.yaml"
perl -pi -e 's/path: minimal\.standard\.squashfs/path: minimal.standard.agentos.squashfs/' \
  "$tree/casper/install-sources.yaml"

mkdir -p "$tree/agentos"
cp "$package" "$tree/agentos/agentos-runtime.deb"
cp "$root/packaging/iso/install-agentos.sh" "$tree/agentos/install-agentos.sh"
chmod 0755 "$tree/agentos/install-agentos.sh"
cp "$root/README.md" "$tree/agentos/README.md"
perl -pi -e 's/Try or Install Ubuntu/Try or Install AgentOS/' "$tree/boot/grub/grub.cfg"
printf 'AgentOS 26.04 arm64 - Ubuntu-based agent operating system\n' > "$tree/.disk/info"
(
  cd "$tree"
  find . -type f ! -name md5sum.txt -print0 | xargs -0 md5 -r > md5sum.txt
)

rm -f "$output_iso"
xorriso -indev "$source_iso" -outdev "$output_iso" \
  -map "$tree" / \
  -boot_image any replay \
  -volid "AgentOS 26.04 arm64" \
  -commit
printf '%s\n' "$output_iso"
