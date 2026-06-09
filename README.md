# AgentOS

AgentOS is an agent-first operating experience built on Ubuntu 24.04 LTS. It
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

It is not yet an installable Ubuntu image. Image building, desktop shell,
provider adapters, and privileged helper implementations are roadmap items.

## Quick start

Requires Python 3.11+ and has no third-party runtime dependencies.

```bash
make test
make run
curl http://127.0.0.1:7788/v1/health
```

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
