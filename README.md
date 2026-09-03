# AgentOS

**Your computer, run by agents you talk to.**

AgentOS is a desktop operating system built on Ubuntu 26.04 LTS. Install it
like any OS. On first boot, tell it your name and pick an AI agent — a fully
offline local model (bundled, no account needed) or a cloud agent like Claude,
ChatGPT, Gemini, and many more. After that, press `Super+Space` anywhere and
just type what you want done: *"organize my downloads folder"*, *"write an
email to my boss"*, *"install Spotify"* — agents do it.

All your regular Ubuntu apps still work. The agent layer is on top, not a
replacement.

---

## Get AgentOS

Download the latest ISO and its checksum file (`agentos-26.04-desktop-arm64.iso`
and `.sha256`) from the project's releases.

Verify the download before installing:

```bash
sha256sum -c agentos-26.04-desktop-arm64.iso.sha256
```

### System requirements

- 64-bit ARM (arm64) machine — current ISO targets Apple Silicon VMs and
  arm64 desktops/laptops.
- 8 GB RAM minimum (16 GB recommended if you'll run a local AI model).
- 25 GB free disk space (local AI models add a few GB more).
- Internet connection for cloud agents (optional — local AI works fully
  offline).

## Install

1. Flash the ISO to a USB drive (e.g. with Rufus, Etcher, or `dd`), or boot it
   directly in a VM.
2. Boot from it and choose **Install AgentOS**. This is the standard Ubuntu
   installer — same steps as installing regular Ubuntu (disk, language,
   username, password).
3. Reboot when prompted.

## First boot

A short setup wizard greets you — three steps, no terminal required:

1. **What should we call you?** — your name, used to personalize the desktop.
2. **Connect an agent** — "Local AI" is pre-selected and ready to go with zero
   setup (the model runs entirely on your machine, fully offline). Or pick a
   cloud agent — Claude, OpenAI, Gemini, Grok, OpenRouter, DeepSeek, Mistral,
   Groq, and many more — and paste your API key. There's also an
   **"Other / custom provider"** option for connecting any OpenAI-compatible
   service by URL.
3. **Pick a model** — choose the default model for your chosen agent.

That's it — AgentOS is ready to use.

## Using AgentOS

- **Press `Super+Space`** anywhere to open the AgentOS chat bar. Type a
  request in plain English and the relevant agent handles it — opening apps,
  organizing files, drafting messages, installing software, and more.
- **Everything stays visible.** Agents ask for approval before anything
  risky (deleting files, installing packages, sending messages) and log every
  action.
- **Traditional desktop still works.** Files, Settings, browser, terminal —
  all there, untouched.
- **Switch or add agents anytime** from Settings → "Re-run onboarding wizard".

## Troubleshooting

- **Local AI seems slow on first use** — the wizard downloads a small model
  (~2 GB) the first time you pick "Local AI". This only happens once.
- **"No models found" for a cloud agent** — double-check the API key and that
  your account has an active plan for that provider.
- **Want to change agents later** — open Settings and choose "Re-run
  onboarding wizard" to reconnect.
- **Chat bar doesn't appear** — log out and back in once (registers the
  `Super+Space` shortcut), or run `agentos-launcher --toggle` from a terminal.

---

## For developers

AgentOS's control plane is a small, auditable Python 3.11+ codebase with no
third-party runtime dependencies — agent registration, policy/RBAC, a
vendor-neutral LLM gateway (20+ providers + custom endpoints), SQLite-backed
runtime/audit storage, and a GTK4 + libadwaita desktop shell.

```bash
make test     # run the test suite
make run      # start the daemon
make package  # build the .deb
scripts/remaster_iso.sh  # build the ISO (requires xorriso, squashfs-tools,
                          # and ubuntu-26.04-desktop-arm64.iso in repo root)
```

Design principles, architecture, and roadmap docs:

- [Architecture](docs/architecture.md)
- [Service design](docs/services.md)
- [API and agent protocol](docs/protocol.md)
- [Security model](docs/security.md)
- [Desktop experience](docs/desktop.md)
- [Installation workflow](docs/installation.md)
- [Roadmaps](docs/roadmap.md)

Contributions welcome — open an issue or PR.

## License

Apache-2.0. See [LICENSE](LICENSE).
