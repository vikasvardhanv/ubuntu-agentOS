#!/bin/bash
# remaster_iso.sh — Build AgentOS ISO from an Ubuntu 26.04 Desktop ARM64 base.
#
# Dependencies (install on your build host):
#   apt install xorriso squashfs-tools 7zip
#
# Usage:
#   scripts/remaster_iso.sh [SOURCE_ISO [OUTPUT_ISO]]
#
# The SOURCE_ISO defaults to ubuntu-26.04-desktop-arm64.iso in the repo root.
# The OUTPUT_ISO defaults to dist/agentos-26.04-desktop-arm64.iso.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_iso="${1:-$root/ubuntu-26.04-desktop-arm64.iso}"
output_iso="${2:-$root/dist/agentos-26.04-desktop-arm64.iso}"
tree="$root/build/iso-tree"
overlay="$root/build/iso-overlay"
version="${AGENTOS_VERSION:-0.3.0}"
package="$root/dist/agentos-runtime_${version}_all.deb"

# ------------------------------------------------------------------ preflight

check_tool() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: '$1' not found. Install it with: apt install $2" >&2
        exit 1
    }
}
check_tool xorriso xorriso
check_tool mksquashfs squashfs-tools
# 7z (from 7zip or p7zip-full) is the most reliable cross-platform ISO extractor.
# Fall back to xorriso itself if 7z is absent.
if command -v 7z >/dev/null 2>&1; then
    ISO_EXTRACT_CMD="7z"
elif command -v 7za >/dev/null 2>&1; then
    ISO_EXTRACT_CMD="7za"
else
    ISO_EXTRACT_CMD="xorriso"
fi

[ -f "$source_iso" ] || {
    echo "ERROR: source ISO not found: $source_iso" >&2
    echo "Download Ubuntu 26.04 Desktop ARM64 and place it there, or pass the path as \$1." >&2
    exit 1
}

# Build the .deb first if it doesn't exist.
[ -f "$package" ] || AGENTOS_VERSION="$version" "$root/scripts/build_deb.sh"

# ------------------------------------------------------------------ extract ISO

if [ -d "$tree" ]; then
    chmod -R u+w "$tree"
    rm -rf "$tree"
fi
rm -rf "$overlay"
mkdir -p "$tree" "$overlay" "$(dirname "$output_iso")"

echo "Extracting ISO → $tree"
if [ "$ISO_EXTRACT_CMD" = "xorriso" ]; then
    # xorriso can copy-out the ISO filesystem without mounting it.
    xorriso -indev "$source_iso" -osirrox on -extract / "$tree" 2>/dev/null
else
    "$ISO_EXTRACT_CMD" x "$source_iso" -o"$tree" -y >/dev/null
fi
chmod -R u+w "$tree"

# ------------------------------------------------------------------ build AgentOS filesystem overlay
#
# We construct a minimal squashfs layer containing only AgentOS files so that
# Ubuntu's live installer can stack it on top of the base layers.
# The overlay is built straight from the built .deb's data.tar.gz (build_deb.sh
# stages into a throwaway mktemp dir, so we can't rely on it surviving).

echo "Extracting AgentOS package → $overlay"
deb_extract="$root/build/deb-extract"
rm -rf "$deb_extract"
mkdir -p "$deb_extract"
(cd "$deb_extract" && ar x "$package")
tar -xzf "$deb_extract/data.tar.gz" -C "$overlay"

# Enable services via static symlinks so they start without running systemctl.
mkdir -p \
    "$overlay/etc/systemd/system/multi-user.target.wants" \
    "$overlay/etc/systemd/system/graphical.target.wants"

ln -sf /lib/systemd/system/agentos-runtime.service \
    "$overlay/etc/systemd/system/multi-user.target.wants/agentos-runtime.service"
ln -sf /lib/systemd/system/agentos-firstboot.service \
    "$overlay/etc/systemd/system/graphical.target.wants/agentos-firstboot.service"

# ------------------------------------------------------------------ bundle Ollama (local AI, offline day one)
#
# Stages the Ollama server binary into the image so the first-boot wizard's
# "Local AI (Ollama)" option works with zero network access and no API key.
# Set AGENTOS_SKIP_OLLAMA=1 to skip (e.g. on build hosts without network).
# Set AGENTOS_BUNDLE_MODEL=<name> (default qwen2.5:3b) to also pre-pull a
# default model into the image so first chat works fully offline; this adds
# several GB to the ISO and requires `ollama` on the build host.

if [ "${AGENTOS_SKIP_OLLAMA:-0}" != "1" ]; then
    ollama_url="https://ollama.com/download/ollama-linux-arm64.tgz"
    ollama_cache="$root/build/ollama-linux-arm64.tgz"

    echo "Staging Ollama (local AI runtime)…"
    mkdir -p "$root/build"
    if [ ! -f "$ollama_cache" ]; then
        if ! curl -fsSL "$ollama_url" -o "$ollama_cache"; then
            echo "WARNING: could not download Ollama ($ollama_url) — skipping bundling." >&2
            rm -f "$ollama_cache"
        fi
    fi

    if [ -f "$ollama_cache" ]; then
        ollama_extract="$root/build/ollama-extract"
        rm -rf "$ollama_extract"
        mkdir -p "$ollama_extract"
        tar -xzf "$ollama_cache" -C "$ollama_extract"

        mkdir -p "$overlay/usr/local/bin" "$overlay/usr/local/lib"
        cp "$ollama_extract/bin/ollama" "$overlay/usr/local/bin/ollama"
        chmod 0755 "$overlay/usr/local/bin/ollama"
        [ -d "$ollama_extract/lib/ollama" ] && \
            cp -R "$ollama_extract/lib/ollama" "$overlay/usr/local/lib/ollama"

        install -d "$overlay/lib/systemd/system"
        cp "$root/packaging/systemd/ollama.service" "$overlay/lib/systemd/system/ollama.service"
        ln -sf /lib/systemd/system/ollama.service \
            "$overlay/etc/systemd/system/multi-user.target.wants/ollama.service"

        if [ -n "${AGENTOS_BUNDLE_MODEL:-}" ] && command -v ollama >/dev/null 2>&1; then
            model="$AGENTOS_BUNDLE_MODEL"
            echo "Pre-pulling $model into the image (this can take a while)…"
            model_store="$overlay/var/lib/ollama/models"
            mkdir -p "$model_store"
            OLLAMA_MODELS="$model_store" ollama pull "$model" || \
                echo "WARNING: failed to pre-pull $model — first run will download it instead." >&2
        fi
        echo "Ollama bundled."
    fi
fi

# ------------------------------------------------------------------ autoinstall (subiquity) config
#
# Injects a minimal autoinstall config so Subiquity knows to call our
# install hook after the base system is laid down.

autoinstall_dir="$tree/autoinstall"
mkdir -p "$autoinstall_dir"
cat > "$autoinstall_dir/user-data" <<'AUTOINSTALL'
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: agentos
    username: agent
    password: '$6$rounds=4096$agentOS$'   # set during onboarding
  locale: en_US.UTF-8
  keyboard:
    layout: us
  storage:
    layout:
      name: lvm
  apt:
    disable_components: []
  packages:
    - python3
  late-commands:
    # Install AgentOS runtime from the bundled .deb on the live medium.
    - curtin in-target --target=/target -- sh -c 'dpkg -i /cdrom/agentos/agentos-runtime.deb || true'
    - curtin in-target --target=/target -- systemctl enable agentos-runtime.service agentos-firstboot.service
AUTOINSTALL

# Empty meta-data required by cloud-init / Subiquity.
touch "$autoinstall_dir/meta-data"

# ------------------------------------------------------------------ build the squashfs layer

echo "Building AgentOS squashfs layer…"
mksquashfs "$overlay" "$tree/casper/minimal.agentos.squashfs" \
    -quiet -no-recovery -no-xattrs -all-root -noappend

cp "$tree/casper/minimal.agentos.squashfs" \
   "$tree/casper/minimal.standard.agentos.squashfs"

overlay_size="$(du -sk "$overlay" | awk '{print $1 * 1024}')"
printf '%s\n' "$overlay_size" > "$tree/casper/minimal.agentos.size"
printf '%s\n' "$overlay_size" > "$tree/casper/minimal.standard.agentos.size"

# Update manifests to include our package.
for suffix in "" ".standard"; do
    base="$tree/casper/minimal${suffix}"
    cp "${base}.manifest"      "${base}.agentos.manifest"
    cp "${base}.manifest.full" "${base}.agentos.manifest.full"
    printf 'agentos-runtime\t%s\n' "$version" >> "${base}.agentos.manifest"
    printf 'agentos-runtime\t%s\n' "$version" >> "${base}.agentos.manifest.full"
done

# Point the install-sources config at our layers.
if [ -f "$tree/casper/install-sources.yaml" ]; then
    perl -pi -e 's{path: minimal\.squashfs}{path: minimal.agentos.squashfs}g' \
        "$tree/casper/install-sources.yaml"
    perl -pi -e 's{path: minimal\.standard\.squashfs}{path: minimal.standard.agentos.squashfs}g' \
        "$tree/casper/install-sources.yaml"
fi

# ------------------------------------------------------------------ place .deb and installer helper

mkdir -p "$tree/agentos"
cp "$package"                                  "$tree/agentos/agentos-runtime.deb"
cp "$root/packaging/iso/install-agentos.sh"   "$tree/agentos/install-agentos.sh"
chmod 0755 "$tree/agentos/install-agentos.sh"
cp "$root/README.md" "$tree/agentos/README.md"

# ------------------------------------------------------------------ branding

# GRUB menu (if present — EFI and legacy BIOS).
for grubcfg in \
        "$tree/boot/grub/grub.cfg" \
        "$tree/EFI/boot/grub.cfg" \
        "$tree/efi/boot/grub.cfg"; do
    [ -f "$grubcfg" ] && \
        perl -pi -e 's/Try or Install Ubuntu/Try or Install AgentOS/g' "$grubcfg"
done

printf 'AgentOS 26.04 arm64 - Ubuntu-based agent operating system\n' > "$tree/.disk/info"

# ------------------------------------------------------------------ MD5 checksums (GNU md5sum)

echo "Computing checksums…"
(
    cd "$tree"
    find . -type f ! -name 'md5sum.txt' -print0 \
        | xargs -0 md5sum \
        > md5sum.txt
)

# ------------------------------------------------------------------ repack ISO with xorriso

echo "Repacking ISO → $output_iso"
rm -f "$output_iso"
xorriso -indev "$source_iso" \
        -outdev "$output_iso" \
        -map "$tree" / \
        -boot_image any replay \
        -volid "AgentOS 26.04 arm64" \
        -commit

# ------------------------------------------------------------------ checksum for downloads

echo "Computing SHA-256 checksum…"
(cd "$(dirname "$output_iso")" && sha256sum "$(basename "$output_iso")" > "$(basename "$output_iso").sha256")

printf '\nOutput:   %s\n' "$output_iso"
printf 'Checksum: %s.sha256\n' "$output_iso"
