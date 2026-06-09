# Delivery Roadmap

## MVP: single-device developer preview

- Runtime, policy, registry, audit, and gateway daemons
- SQLite WAL persistence and local encrypted secret integration
- Ollama plus two hosted provider adapters
- Filesystem, terminal, browser, Git, notification, and search tools
- System, File, Terminal, Browser, Git, and Research agents
- GNOME shell extension with palette, workspace, timeline, and approvals
- Ubuntu package repository and developer ISO
- Threat model, security tests, crash recovery, and audit export

Exit criteria: all side effects are policy controlled and audited; no agent runs
as root; restart and retry do not duplicate actions; an offline workflow works.

## Production 1.0

- All specified provider adapters and system services
- Signed tool/agent SDK and third-party registry
- PostgreSQL/pgvector, knowledge graph, durable event bus, HA runtime
- Enterprise SSO, tenant isolation, fleet policy, SIEM export, key management
- Kubernetes, cloud, DataOps, and Security agents
- Reproducible signed images, secure/measured boot, OTA rollback
- Accessibility, localization, telemetry controls, support tooling
- Independent security review and sustained load/failure testing

## Later platform work

- Confidential compute and microVM isolation profiles
- Federated/private memory and policy-aware multi-device workflows
- Formal policy verification and action simulation
- Marketplace governance and compatibility certification
