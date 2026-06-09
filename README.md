# AgentOS

AgentOS is an agent-first operating experience built on Ubuntu LTS. The current
ARM64 development image is based on the supplied Ubuntu 26.04 desktop ISO. It
keeps the Ubuntu kernel and hardware enablement stack unchanged and adds a
policy-controlled agent control plane, system services, and desktop shell.

This repository is the production architecture baseline and a runnable
reference implementation of the AgentOS control plane. It is intentionally
small enough to audit. The runtime defaults to local-only networking,
deny-by-default authorization, approval-gated privileged actions, and
append-only audit logging.

## Repository status

The first milestone includes:

- Agent registration, lifecycle, task planning, and action dispatch
- Policy decisions with RBAC and human approval gates
- Tool registry with permission metadata
- Vendor-neutral model routing policy
- SQLite schema for runtime, memory, approvals, and audit data
- Versioned HTTP, event, and agent manifest contracts
- Hardened systemd and D-Bus integration definitions
- Architecture, security, desktop, installation, and roadmap specifications

The development image is installable, but it is not yet a production release.
Desktop shell, native provider adapters, privileged helper implementations,
signing, and hardware qualification remain roadmap items.

The repository now includes a reproducible remastering path that embeds the
runtime into Ubuntu's layered installer. The generated development image is
`dist/agentos-26.04-desktop-arm64.iso`.

## Quick start

Requires Python 3.11+ and has no third-party runtime dependencies.

```bash
make test
make run
curl http://127.0.0.1:7788/v1/health
```

## Build the ARM64 image

Requires `xorriso` and `squashfs-tools`, and expects the source image at
`ubuntu-26.04-desktop-arm64.iso`.

```bash
make package
scripts/remaster_iso.sh
```

The remaster preserves Ubuntu's boot metadata, adds AgentOS filesystem layers
to both minimal and full installation choices, enables first-boot onboarding,
and includes the standalone Debian package under `/agentos`.

The server stores state under `./var` by default. Override settings with
environment variables documented in [`config/agentos.env`](config/agentos.env).

## Design principles

1. Agents never receive ambient root access.
2. Every consequential request becomes an immutable action and audit event.
3. Policy is evaluated before dispatch and again at privileged boundaries.
4. Provider credentials stay in the gateway credential boundary.
5. Local execution and storage are the default; remote services are explicit.
6. APIs and events are versioned so independent services can evolve safely.

## Documentation

- [Architecture](docs/architecture.md)
- [Service design](docs/services.md)
- [API and agent protocol](docs/protocol.md)
- [Security model](docs/security.md)
- [Desktop experience](docs/desktop.md)
- [Installation workflow](docs/installation.md)
- [Roadmaps](docs/roadmap.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
