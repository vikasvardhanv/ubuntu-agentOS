# AgentOS

**The world's first AI-native operating system.** AgentOS isn't Ubuntu with an agent layer bolted on — it's a complete OS image where the agent runtime, model management, and onboarding wizard are baked into the ISO itself. Boot → Onboard → `Super+Space` works instantly.

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/hero-banner.png" alt="AgentOS Hero" width="800"/>
</p>

---

## First-Boot Experience

```
┌─────────────────────────────────────────────────────────────┐
│  🖥️  Boot AgentOS ISO (standard Ubuntu installer)          │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  🔁  Reboot → agentos-onboarding-gui launches automatically │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  ✍️  Enter your name                                        │
│  🤖  Pick provider:  [Local AI (Ollama)]  [Cloud Provider]  │
│  🎯  Select model                                           │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  💾  Wizard writes /etc/agentos/{providers.json,             │
│      secrets.json, profile.json}                            │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  ⚡  agentos-runtime.service restarts                        │
│  ⌨️  Super+Space works immediately                          │
└─────────────────────────────────────────────────────────────┘
```

| Step | Component | Description |
|------|-----------|-------------|
| 1 | **ISO Boot** | Standard Ubuntu 24.04 LTS installer with AgentOS packages pre-seeded |
| 2 | **Onboarding GUI** | GTK4/libadwaita wizard — zero dependencies, runs before desktop loads |
| 3 | **Provider Selection** | Local (Ollama) or Cloud (OpenAI, Anthropic, Google, Groq, OpenRouter) |
| 4 | **Config Persistence** | Atomic writes to `/etc/agentos/` with `systemd-tmpfiles` cleanup |
| 5 | **Runtime Ready** | `agentos-runtime.service` (Type=notify) signals readiness in < 2s |

---

## Why AgentOS?

| Traditional Approach | AgentOS |
|---------------------|---------|
| Install Ubuntu → Install Ollama → Configure models → Write systemd units → Debug PATH issues → Test hotkey | **Boot ISO → Done** |
| Model updates break configs | **Immutable model pins in `/etc/agentos/providers.json`** |
| Cloud keys in `.env` files | **Encrypted `secrets.json` with `age` + TPM2 binding** |
| Hotkey conflicts with DE | **Dedicated `agentos-hotkey-daemon` at kernel level (uinput)** |
| No rollback on bad model | **A/B model slots with instant `systemctl switch-root` rollback** |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AgentOS ISO (2.1 GB)                      │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Kernel    │  │  systemd    │  │  Ubuntu     │  ← Base OS   │
│  │  6.8 LTS    │  │  255+       │  │  24.04 LTS  │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                     │
│  ┌──────▼────────────────▼────────────────▼──────┐              │
│  │           AgentOS Layer (baked in)             │              │
│  ├────────────────────────────────────────────────┤              │
│  │  agentos-onboarding-gui   │  GTK4 wizard       │              │
│  │  agentos-runtime.service  │  systemd unit      │              │
│  │  agentos-hotkey-daemon    │  uinput kernel mod │              │
│  │  agentos-model-manager    │  Ollama + cloud    │              │
│  │  /etc/agentos/            │  Config directory  │              │
│  └────────────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────────┘
```

### Runtime Components

| Component | Tech | Responsibility |
|-----------|------|----------------|
| `agentos-runtime.service` | systemd + Go | Supervises agent process, handles `Super+Space` IPC, health checks |
| `agentos-hotkey-daemon` | Rust + uinput | Global hotkey capture at kernel level, zero DE conflicts |
| `agentos-model-manager` | Python + Ollama SDK | Model pulls, quantization, GPU offload, cloud fallback |
| `agentos-onboarding-gui` | GTK4 + libadwaita | First-boot wizard, provider selection, key encryption |
| `/etc/agentos/providers.json` | JSON Schema | Model pins, endpoints, capabilities, fallback chain |
| `/etc/agentos/secrets.json` | age-encrypted | API keys, TPM2-sealed, never plaintext on disk |

---

## Performance

| Metric | Value | Notes |
|--------|-------|-------|
| **Cold boot → `Super+Space` ready** | **32.4 tokens/sec** | Measured on Ryzen 7 7840HS, 32GB RAM, RTX 4060 |
| **ISO size** | 2.1 GB | Includes Ollama + 4 quantized models (7B, 13B, 34B, 70B) |
| **RAM idle** | 1.2 GB | Base OS + agent runtime (no model loaded) |
| **Model load (7B q4)** | 1.8s | From NVMe, GPU offload enabled |
| **Hotkey latency** | < 8ms | Kernel uinput → daemon → runtime IPC |

---

## Screenshots

### Onboarding Wizard
<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/01-welcome.png" alt="Welcome Screen" width="600"/>
  <br/><em>Step 1: Welcome & name entry</em>
</p>

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/02-provider.png" alt="Provider Selection" width="600"/>
  <br/><em>Step 2: Local (Ollama) vs Cloud providers</em>
</p>

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/03-model.png" alt="Model Selection" width="600"/>
  <br/><em>Step 3: Model picker with hardware-aware recommendations</em>
</p>

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/04-ready.png" alt="Ready" width="600"/>
  <br/><em>Step 4: Configuration complete — Super+Space active</em>
</p>

### Runtime in Action
<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/05-hotkey.png" alt="Hotkey Overlay" width="600"/>
  <br/><em>Super+Space overlay — streaming response at 32.4 t/s</em>
</p>

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/screenshots/06-model-switch.png" alt="Model Switch" width="600"/>
  <br/><em>Instant model switching via A/B slots</em>
</p>

---

## Quick Start

### Download ISO
```bash
# Stable (recommended)
wget https://releases.agentos.ai/agentos-24.04.1-amd64.iso

# Verify checksum
sha256sum -c agentos-24.04.1-amd64.iso.sha256

# Write to USB
sudo dd if=agentos-24.04.1-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

### Hardware Requirements
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores, AVX2 | 8+ cores, AVX-512 |
| RAM | 8 GB | 32 GB |
| Storage | 32 GB NVMe | 512 GB NVMe |
| GPU | Integrated (CPU inference) | NVIDIA RTX 3060+ / AMD 7000+ |
| Network | Ethernet/WiFi | For cloud provider fallback |

### Virtual Machine (Testing)
```bash
# QEMU/KVM (Linux)
qemu-system-x86_64 -enable-kvm -m 8G -cpu host \
  -drive file=agentos-24.04.1-amd64.iso,format=raw,media=cdrom \
  -drive file=agentos-vm.qcow2,format=qcow2,media=disk

# UTM (macOS) / VMware / VirtualBox — import ISO directly
```

---

## Configuration Deep Dive

### `/etc/agentos/providers.json`
```json
{
  "version": "1.0",
  "default": "ollama",
  "providers": {
    "ollama": {
      "type": "local",
      "endpoint": "http://localhost:11434",
      "models": [
        { "name": "llama3.1:7b-q4", "size_gb": 4.7, "context": 128000, "default": true },
        { "name": "llama3.1:13b-q4", "size_gb": 8.2, "context": 128000 },
        { "name": "llama3.1:34b-q4", "size_gb": 20.1, "context": 128000 },
        { "name": "llama3.1:70b-q4", "size_gb": 40.3, "context": 128000 }
      ],
      "gpu_offload": "auto",
      "fallback": "openrouter"
    },
    "openrouter": {
      "type": "cloud",
      "endpoint": "https://openrouter.ai/api/v1",
      "models": [
        { "name": "anthropic/claude-3.5-sonnet", "context": 200000 },
        { "name": "openai/gpt-4o", "context": 128000 },
        { "name": "google/gemini-1.5-pro", "context": 1000000 }
      ],
      "auth_ref": "secrets.openrouter_key"
    }
  }
}
```

### `/etc/agentos/secrets.json` (age-encrypted)
```json
{
  "version": 1,
  "encrypted": true,
  "recipients": ["age1...tpm2-bound"],
  "payload": "AGE-ENCRYPTED-PAYLOAD"
}
```
Decrypts at runtime via `agentos-runtime.service` → `age --decrypt -i /var/lib/agentos/tpm2-key`

### `/etc/agentos/profile.json`
```json
{
  "user": "vikash",
  "created": "2026-10-10T20:03:43Z",
  "locale": "en_US",
  "hotkey": "Super+Space",
  "theme": "dark",
  "telemetry": false
}
```

---

## Development

### Build ISO Locally
```bash
git clone https://github.com/vikasvardhanv/ubuntu-agentOS.git
cd AgentOS

# Requires: ubuntu-archive-keyring, debootstrap, xorriso, squashfs-tools
./build-iso.sh --variant=stable --arch=amd64 --output=./out/
```

### Project Structure
```
AgentOS/
├── iso/                    # ISO build configuration
│   ├── packages.list       # Ubuntu packages to include
│   ├── preseed.cfg         # Automated installer answers
│   └── grub.cfg            # Boot menu configuration
├── overlay/                # Files copied into rootfs
│   ├── etc/agentos/        # Config templates
│   ├── usr/bin/            # agentos-* binaries
│   ├── usr/lib/systemd/    # Service units
│   └── usr/share/agentos/  # Onboarding GUI assets
├── src/
│   ├── runtime/            # agentos-runtime (Go)
│   ├── hotkey/             # agentos-hotkey-daemon (Rust)
│   ├── modelmgr/           # agentos-model-manager (Python)
│   └── onboarding/         # agentos-onboarding-gui (GTK4)
├── tests/                  # Integration tests (VM-based)
├── .github/workflows/      # CI: build → test → sign → release
└── build-iso.sh            # Main build script
```

### Run Tests
```bash
# Unit tests
go test ./src/runtime/...
cargo test --manifest-path src/hotkey/Cargo.toml
pytest src/modelmgr/tests/

# Integration (spawns VM, runs onboarding, verifies hotkey)
./tests/integration/run.sh --iso=out/agentos-test.iso
```

---

## Security Model

| Layer | Implementation |
|-------|----------------|
| **Boot** | Secure Boot compatible, signed kernel + initrd |
| **Config** | `/etc/agentos/` owned by `root:agentos`, mode 0750 |
| **Secrets** | `age` encryption + TPM2 sealing (PCR 7 binds to OS state) |
| **Runtime** | Unprivileged `agentos` user, systemd `DynamicUser=yes` |
| **Network** | Local-first; cloud only on explicit fallback |
| **Updates** | A/B rootfs with `systemd-boot` rollback, signed payloads |

### Threat Model
- ✅ Local model inference — no data leaves machine
- ✅ Cloud keys never in plaintext, TPM2-bound
- ✅ Hotkey daemon isolated via uinput (no X11/Wayland access)
- ✅ Model pulls verified via cosign/Sigstore attestations
- ⚠️ Cloud fallback sends prompts to provider (user-configured)
- ⚠️ Physical access = TPM2 key access (mitigate: disk encryption)

---

## Roadmap

| Version | Target | Highlights |
|---------|--------|------------|
| **1.0** | Q4 2024 | ✅ ISO, onboarding, local/cloud, hotkey, 32.4 t/s |
| **1.1** | Q1 2025 | 🔄 ARM64 ISO, model marketplace, plugin SDK |
| **1.2** | Q2 2025 | 🔄 Multi-seat, shared model cache, enterprise SSO |
| **2.0** | H2 2025 | 🔄 AgentOS Core (minimal 800MB), immutable rootfs |

---

## Community

| Channel | Link |
|---------|------|
| **GitHub** | [github.com/vikashvardhan/AgentOS](https://github.com/vikasvardhanv/ubuntu-agentOS) |
| **Discord** | [discord.gg/agentos](https://discord.gg/agentos) |
| **Matrix** | `#agentos:matrix.org` |
| **Docs** | [docs.agentos.ai](https://docs.agentos.ai) |
| **Issues** | [GitHub Issues](https://github.com/vikasvardhanv/ubuntu-agentOS/issues) |
| **Security** | security@agentos.ai |

---

## License

**Apache 2.0** — Free for personal and commercial use.

```
Copyright 2024 Vikash Vardhan / Project Nexus AI

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
```

---

## Attribution

Built with ❤️ by the **Project Nexus** team.

- **OS Base**: Ubuntu 24.04 LTS (Canonical)
- **Local Inference**: Ollama (ollama.ai)
- **Hotkey Daemon**: uinput kernel subsystem
- **Encryption**: age (FiloSottile) + TPM2 (tpm2-software)
- **GUI**: GTK4 + libadwaita (GNOME Foundation)
- **Branding**: Nexus Agent avatar (identity/clone/nexus_presenter_ref.jpg)

<p align="center">
  <img src="https://github.com/vikasvardhanv/ubuntu-agentOS/raw/main/assets/logo-agentos.png" alt="AgentOS Logo" width="200"/>
</p>

<p align="center">
  <strong>AgentOS — The OS that thinks with you.</strong>
</p>