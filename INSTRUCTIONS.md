# AgentOS: Build, Remaster, Install & Onboard Guide

This guide is designed as a standalone instruction set (or AI developer prompt) to build and deploy AgentOS. By following these clean, minimal instructions, you will package the control plane, remaster the Ubuntu ISO, install the operating system, and connect it to any LLM provider of your choice.

---

## 1. System Overview

AgentOS is an agent-first operating experience built on top of Ubuntu Desktop (LTS). It introduces:
1. **Agent Runtime & local daemon (`agentosd`)**: Listens on `http://127.0.0.1:7788` for agent registration, lifecycle management, and action dispatching.
2. **LLM Routing Gateway**: Exposes an OpenAI-compatible `/v1/chat/completions` endpoint that handles fallback routing, circuit breaking, and normalization across Ollama, OpenAI, Anthropic, Gemini, Grok, and custom endpoints.
3. **Policy & Audit**: Hardened local policy controls (RBAC/ABAC) and hash-chained audit logging to secure agent actions.
4. **First-Boot Onboarding Wizard**: A system utility that runs on first boot to discover available models from any user-selected provider (local or remote) and configure defaults securely.

---

## 2. Prerequisites

To build and remaster the ISO, you will need the following dependencies on your build host:
- **Python**: 3.11 or later
- **ISO tools**: `xorriso` and `squashfs-tools` (e.g. `brew install xorriso` or `sudo apt install xorriso squashfs-tools`)
- **Ubuntu Base Image**: A standard ARM64 Ubuntu Desktop ISO placed at the root of this folder as `ubuntu-26.04-desktop-arm64.iso`.

---

## 3. Development and Local Testing

You can test the daemon locally before building the ISO:

### Step 1: Install Python dependencies (if any) and initialize database
```bash
make init-db
```
This generates the SQLite database schema under `./var/agentos.db`.

### Step 2: Run Unit Tests
```bash
make test
```
Verifies routing, gateway fallback, and policy engine logic.

### Step 3: Run the Daemon Locally
```bash
make run
```
Starts `agentosd` at `http://127.0.0.1:7788`. You can check its health at:
```bash
curl http://127.0.0.1:7788/v1/health
```

---

## 4. Packaging and Remastering the ISO

To bundle AgentOS into a bootable Ubuntu ISO, execute the build pipeline:

```bash
# 1. Compile, run tests, and package the code into a Debian package (.deb)
make package

# 2. Extract the base Ubuntu ISO, layer the debian package, configure systemd, and remaster
scripts/remaster_iso.sh
```

This generates the custom installer image at:
```text
dist/agentos-26.04-desktop-arm64.iso
```

By default `remaster_iso.sh` also downloads the Ollama ARM64 binary and bundles it
into the image (`ollama.service`, `/usr/local/bin/ollama`) so "Local AI (Ollama)" works
fully offline. Set `AGENTOS_SKIP_OLLAMA=1` to skip this (e.g. no network on the build
host), or `AGENTOS_BUNDLE_MODEL=qwen2.5:3b` to also pre-pull a default model into the
image (adds several GB, requires `ollama` on the build host).

---

## 5. OS Installation & LLM Connection

Once the ISO is generated, follow these steps to install and onboard:

1. **Boot the ISO**: Load `dist/agentos-26.04-desktop-arm64.iso` in a virtual machine (e.g., UTM on Mac, QEMU, or bare metal).
2. **Install Ubuntu**: Run through the standard, secure Ubuntu desktop installation wizard.
3. **First-Boot Onboarding (GUI)**: On first login, `agentos-firstboot.service` launches the
   `agentos-onboarding-gui` wizard (falls back to the terminal wizard, `agentos-onboarding`,
   if no graphical session is available). Three steps:
   - **Name** — what should AgentOS call you.
   - **Connect an agent** — a gateway picker covering ~20 providers. "Local AI (Ollama)"
     is pre-selected and needs no API key (the binary is bundled in the ISO, see step 4 of
     the build). Other local options (LM Studio, vLLM) and cloud options (Claude/Anthropic,
     OpenAI, Gemini, Grok, OpenRouter, DeepSeek, Mistral, Groq, Together, Fireworks, Cerebras,
     Moonshot, Z.AI, MiniMax, Alibaba Qwen, Nous) reveal an API-key field when selected.
     A final **Other / custom provider** option connects any OpenAI-compatible endpoint by
     name + base URL (with an optional API key), so users aren't limited to the built-in list.
     The wizard tests the connection and, for Ollama with no models yet, automatically
     `ollama pull`s a small recommended default (`llama3.2:3b`).
   - **Model** — pick the default model from those discovered.
4. **Activate**: The wizard writes `/etc/agentos/providers.json` + `/etc/agentos/secrets.json`
   (via `agentos.onboarding_core`, shared with the CLI wizard), writes your name to
   `/etc/agentos/profile.json`, and restarts `agentos-runtime.service`.
5. **Use it**: Press `Super+Space` anywhere to open the AgentOS launcher
   (`agentos-launcher`, an always-on-top chat bar) — type a request and agents handle it.
   The full desktop shell (`agentos-shell`) is available for Agents/Tasks/Approvals/Audit/Settings.

All agent calls requesting `model: "auto"` are transparently routed to your chosen LLM via
the gateway in `agentos/gateway/` (fallback routing, retries, circuit breaking). To connect
a different agent/provider later, re-run `agentos-onboarding-gui` from Settings → "Re-run
onboarding wizard".
