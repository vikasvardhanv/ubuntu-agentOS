# Security Model

## Invariants

- No agent or model process runs as root.
- Deny is the default when policy, identity, schema, or approval is unavailable.
- Privileged operations are typed, allowlisted, and re-authorized at the broker.
- Every action, decision, approval, invocation, and result is audited.
- Secrets are referenced, never exposed to models or stored in task payloads.
- Remote content, tool output, and model output are untrusted data.
- Provider credentials exist only in the gateway service environment and are
  never included in API responses or audit records.

## Authorization

RBAC grants broad job functions. ABAC narrows them using tenant, user, device,
resource, data classification, time, network, and risk. The effective result is
the intersection of role grants, resource policy, and runtime constraints.
High-risk capabilities require fresh human approval and cannot be delegated.

Default risk examples:

| Risk | Examples | Default |
|---|---|---|
| Read | Granted files, health metrics | Allow within grant |
| Modify | Write user files, create branch | Approval by policy |
| External side effect | Send message, deploy, purchase | Fresh approval |
| Privileged | Packages, users, firewall, services | Broker + fresh approval |
| Prohibited | Disable audit, unrestricted root shell | Deny |

## Isolation

Tool workers run in transient systemd scopes with `NoNewPrivileges`, private
temporary directories, syscall filters, capability bounding, resource limits,
and network restrictions. Higher-risk workloads use containers or microVMs.
Filesystem tools resolve symlinks and verify the final canonical path remains
inside a granted root.

The development gateway binds to loopback. Operators should set
`AGENTOS_API_TOKEN` through a protected systemd credential for Bearer
authentication. A production desktop build must replace header-supplied actor
roles with Unix-socket peer credentials and signed session claims.

## Audit

Audit records are append-only and hash chained. Production deployments sign
checkpoints with a TPM-backed key and export them to immutable remote storage.
Audit access is itself audited. Payloads are minimized and sensitive values are
redacted before persistence.

## Threats addressed

Prompt injection cannot grant capabilities because authorization is external
to the model. Confused-deputy attacks are reduced by binding decisions to
actor, action, resource, arguments hash, and expiration. SSRF is constrained by
network policy and destination validation. Supply-chain risk is controlled by
signed agent/tool manifests, measured artifacts, and staged updates.
