# AgentOS Architecture

## System position

AgentOS is an Ubuntu 24.04 LTS derivative. It does not replace the Linux
kernel, drivers, systemd, NetworkManager, PipeWire, portals, or Ubuntu security
updates. It adds a control plane and desktop experience that make goal-driven
agent workflows the primary interaction model.

```text
AgentOS Shell / CLI / Enterprise API
                 |
        Local API Gateway (Unix socket)
                 |
  +--------------+-------------------+
  | Runtime | Policy | Audit | Memory|
  +--------------+-------------------+
                 |
       Capability Tool Registry
                 |
  Unprivileged services / xdg-desktop-portal
                 |
   approval-gated privileged broker (D-Bus)
                 |
 Ubuntu 24.04: systemd, kernel, devices, network
```

## Trust boundaries

1. **User session:** Shell, workspace, user agents, and most tools run as the
   logged-in user with systemd user units and sandboxing.
2. **Control plane:** Runtime, policy, gateway, memory, and audit services have
   separate Unix users, writable directories, and Unix sockets.
3. **Provider boundary:** Only the gateway can resolve model credentials.
4. **Privileged boundary:** A minimal root broker exposes allowlisted,
   typed D-Bus operations. It independently validates signed approval grants.
5. **External boundary:** Cloud, Git, Kubernetes, and browser connectors use
   scoped credentials and explicit egress policy.

## Core components

| Component | Responsibility | Persistent state |
|---|---|---|
| Agent Runtime | Agent lifecycle, goals, plans, actions, scheduling | PostgreSQL/SQLite |
| Agent Gateway | Provider adapters, routing, quotas, redaction | Encrypted secrets, metrics |
| Memory | Sessions, durable facts, embeddings, graph edges | PostgreSQL + pgvector |
| Policy Engine | RBAC, ABAC, risk, approval grants | Policy bundles, approvals |
| Tool Registry | Typed tools, capability discovery, invocation | Tool manifests |
| Audit Service | Tamper-evident action and decision record | Append-only event store |

SQLite is supported for a single-device installation. Enterprise deployments
use PostgreSQL with pgvector and an object store for large artifacts. The
logical schema remains common.

## Execution model

A goal is decomposed into a plan. Every plan step requests a typed tool action.
The runtime persists the action before asking policy for a decision. Allowed
actions are dispatched to a sandboxed tool worker. Conditional actions wait
for a time-bound human approval grant. Denied actions are terminal. Every
transition emits an audit event containing correlation and causation IDs.

Long operations use leases and heartbeats. Action IDs and idempotency keys
prevent duplicate side effects after retries. Agents communicate through
versioned envelopes; they do not invoke one another directly.

## Scale and availability

- Device mode: one runtime, SQLite WAL, local model support, Unix sockets.
- Team mode: replicated stateless runtimes, PostgreSQL, NATS JetStream, Vault.
- Enterprise mode: regional control planes, tenant isolation, policy bundles,
  immutable audit export, fleet management, and disaster recovery.
- Schedulers use queue partitioning by tenant and capability. Workers advertise
  capacity and capabilities. No action is assigned without a valid lease.

## Repository structure

```text
agentos/             Reference control-plane modules
cmd/agentosd/        Local daemon entry point
api/                 OpenAPI and JSON Schema contracts
db/migrations/       Logical persistence schema
packaging/           systemd and D-Bus integration
config/              Secure defaults
docs/                Product and engineering specifications
tests/               Unit and contract-focused tests
```
