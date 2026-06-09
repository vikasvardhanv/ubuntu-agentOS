# APIs and Agent Communication

The external HTTP contract is in [`api/openapi/agentos.yaml`](../api/openapi/agentos.yaml).
Agent manifests and event envelopes are defined as JSON Schemas under
[`api/schemas`](../api/schemas).

## Versioning

HTTP paths use a major version (`/v1`). Schemas include `schema_version`.
Additive fields are backward compatible. Breaking changes require a new major
version and a migration period. Unknown fields must be ignored by consumers
unless the schema explicitly forbids them.

## Event envelope

Every lifecycle change emits an envelope with:

- globally unique event ID
- event type and schema version
- UTC occurrence time
- tenant, actor, correlation, and causation identifiers
- classification label
- typed data payload
- previous event hash and current hash for audit streams

Events are at-least-once. Consumers deduplicate by event ID. Commands use an
idempotency key. Actions use leases to make worker failure recoverable.

## Action lifecycle

```text
requested -> evaluating -> waiting_approval -> queued -> running
          -> denied       -> cancelled       -> succeeded | failed
```

Policy decisions include `allow`, `deny`, or `require_approval`, plus reasons,
constraints, and expiration. Approval grants are scoped to one action or a
narrow action pattern and expire automatically.

## Tool invocation

A tool call contains an immutable action ID, tool/version, typed arguments,
resource selectors, actor identity, approval grant reference when required,
deadline, and trace context. Tool workers validate the request again before
performing any side effect and return structured output and evidence.
