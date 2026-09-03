# AgentOS Repository Index

> Generated index of `/Users/vikashvardhan/IdeaProjects/ubuntu-agentOS` (AgentOS v0.3.0, Apache-2.0).
> Python 3.11+ control plane, ~6.6k lines across source/tests/schemas, no third-party runtime deps.

## What this project is

AgentOS is a desktop OS built on Ubuntu 26.04 LTS (arm64). A control plane + GTK4/libadwaita
desktop shell lets users talk to agents (`Super+Space` chat bar); agents execute goals
(files, shell, packages, email) behind a policy engine with approval gating and hash-chained
audit logging. A vendor-neutral LLM gateway (OpenAI-compatible, 20+ providers + custom
endpoints) handles routing/fallback/circuit-breaking. Daemon listens on `http://127.0.0.1:7788`.

## Top-level layout

| Path | Purpose |
|---|---|
| `agentos/` | Reference control-plane package (gateway, runtime, policy, audit, shell, onboarding, marketplace, tools, helper) |
| `agents/` | Bundled agents (assistant, shell, file, system) + `registry.json` manifests |
| `cmd/agentosd/` | Daemon entry point (`python -m cmd.agentosd`) |
| `api/` | OpenAPI spec (`openapi/agentos.yaml`, 308 lines) + JSON Schemas (agent manifest, event envelope) |
| `config/` | `config.json`, `providers.json`, `agentos.env` runtime configuration |
| `db/migrations/` | `001_initial.sql` (101 lines) — SQLite schema |
| `docs/` | architecture, services, protocol, security, desktop, installation, roadmap |
| `packaging/` | systemd units (10), D-Bus policy/introspection, sysusers/tmpfiles, firstboot wizard, ISO installer, launcher keybinding |
| `scripts/` | `build_deb.sh`, `remaster_iso.sh`, `init_db.py`, `make_ar.py` |
| `tests/` | unittest suite (5 files, ~1.1k lines) |
| `var/` | Runtime state: `agentos.db` (SQLite + WAL), `audit.jsonl` |
| `INSTRUCTIONS.md` | Standalone build/remaster/install/onboard guide |
| `ycombisetup.sh` | Large (302 KB) standalone setup script |
| `Makefile` | run / run-shell / run-helper / run-agents / run-all / test / check / init-db / package |

## File index

### agentos/ — control plane (core)
| File | Lines | Role |
|---|---|---|
| `agentos/shell/main.py` | 870 | GTK4 + libadwaita desktop shell (chat panel) |
| `agentos/onboarding_gui.py` | 551 | First-boot onboarding wizard (GUI) |
| `agentos/helper/main.py` | 356 | Privileged root helper (D-Bus broker) |
| `agentos/api/server.py` | 271 | Local API server (daemon HTTP surface) |
| `agentos/shell/launcher.py` | 259 | `Super+Space` launcher / toggle |
| `agentos/runtime/service.py` | 255 | Agent runtime: lifecycle, goals, actions |
| `agentos/onboarding_core.py` | 198 | Onboarding logic (provider/model discovery) |
| `agentos/policy/engine.py` | 166 | RBAC/ABAC policy + approval decisions |
| `agentos/onboarding.py` | 105 | Onboarding CLI entry |
| `agentos/audit/log.py` | 90 | Hash-chained append-only audit log |
| `agentos/marketplace/installer.py` | 97 | Agent marketplace installer |
| `agentos/marketplace/registry.py` | 49 | Marketplace registry |
| `agentos/gateway/client.py` | 229 | Gateway client (OpenAI-compatible) |
| `agentos/gateway/providers.py` | 145 | Provider adapters (20+ vendors) |
| `agentos/gateway/service.py` | 124 | Gateway service wiring |
| `agentos/gateway/router.py` | 76 | Fallback routing / circuit breaking |
| `agentos/gateway/health.py` | 47 | Health checks |
| `agentos/gateway/errors.py` | 47 | Error taxonomy |
| `agentos/gateway/discovery.py` | 35 | Model discovery |
| `agentos/tools/registry.py` | 43 | Typed tool/capability registry |
| `agentos/domain/models.py` | 63 | Domain dataclasses |
| `agentos/config.py` | 42 | Config loading |

### agents/ — bundled agents
| File | Lines | Trust | Capability |
|---|---|---|---|
| `agents/assistant_agent.py` | 178 | trusted | llm_inference — conversational agent powering the chat panel |
| `agents/system_agent.py` | 239 | operator | system_info + approved package installs |
| `agents/file_agent.py` | 207 | user | file read/write/list |
| `agents/shell_agent.py` | 201 | operator | policy-approved shell command execution |
| `agents/registry.json` | 37 | — | Agent manifests (name, entry point, capabilities, trust level) |

### cmd/
- `cmd/agentosd/__main__.py`, `__init__.py` (32 lines) — daemon entry (`make run`).

### api/
- `api/openapi/agentos.yaml` (308) — REST API spec.
- `api/schemas/agent-manifest.schema.json` (18), `api/schemas/event-envelope.schema.json` (20).

### config/
- `config/config.json` — daemon/runtime settings.
- `config/providers.json` — LLM provider catalog.
- `config/agentos.env` — environment defaults.

### db/
- `db/migrations/001_initial.sql` (101) — initial SQLite schema (applied via `scripts/init_db.py`).

### tests/ (unittest, `make test`)
- `test_new_components.py` (588), `test_policy_audit_runtime.py` (289), `test_gateway.py` (158), `test_config.py` (19), `test_database.py` (18).

### packaging/
- `systemd/` — 10 units: runtime, helper, launcher, shell, firstboot, assistant/file/shell/system agents, ollama.
- `dbus/` — `dev.agentos.Privileged1.conf` + `.xml` (privileged broker interface).
- `firstboot/` — onboarding units/scripts (`agentos-onboarding`, `-gui`, `.desktop`, `prepare-firstboot.sh`).
- `iso/install-agentos.sh`, `launcher/` (keybind .desktop + setup script), `sysusers/` + `tmpfiles/` confs.

### scripts/
- `build_deb.sh` — build the .deb (`make package`).
- `remaster_iso.sh` — remaster Ubuntu ISO (needs xorriso, squashfs-tools, base ISO in repo root).
- `init_db.py` (18) — create `var/agentos.db`.
- `make_ar.py` (36) — ar archive helper for .deb building.

### docs/
- `architecture.md` — trust boundaries, core components, execution model, scale modes.
- `services.md`, `protocol.md` (API + agent envelope protocol), `security.md`, `desktop.md`, `installation.md`, `roadmap.md`.

### var/ (runtime state, gitignored-ish)
- `agentos.db` (+ `-wal`, `-shm`) — SQLite state; `audit.jsonl` — audit trail.

## Common commands

```bash
make init-db    # create SQLite schema in var/agentos.db
make test       # unittest discover -s tests
make run        # daemon at http://127.0.0.1:7788 (health: /v1/health)
make run-all    # daemon + all 4 bundled agents
make package    # build .deb (scripts/build_deb.sh)
scripts/remaster_iso.sh  # build bootable ISO
```

## Key architecture facts (from docs/architecture.md)

- 5 trust boundaries: user session / control plane / provider boundary / privileged D-Bus broker / external connectors.
- Execution model: goal → plan → typed tool action; policy decides allow/deny/approve; every transition emits an audit event with correlation/causation IDs; leases + idempotency keys guard retries.
- Scale modes: device (SQLite WAL, Unix sockets) → team (PostgreSQL, NATS, Vault) → enterprise (regional control planes, tenant isolation).
