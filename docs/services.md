# Service Design

## Control-plane services

| Service | Interface | Key behavior |
|---|---|---|
| `agentos-runtime` | Unix socket HTTP + event bus | Registers agents, owns goals/plans/actions, dispatches tools |
| `agentos-policy` | Unix socket / embedded library | Evaluates subject, capability, resource, context, and risk |
| `agentos-gateway` | OpenAI-compatible local endpoint | Routes OpenAI, Anthropic, Gemini, Grok, Ollama, OpenRouter, and vLLM |
| `agentos-memory` | Internal gRPC/HTTP | Session memory, durable memory, vector search, knowledge graph |
| `agentos-audit` | Event consumer + query API | Hash-chained append-only events and external export |
| `agentos-tools` | Registry API | Validates manifests, discovers workers, dispatches typed calls |

Each production service gets a distinct Linux identity and systemd unit.
Communication defaults to Unix sockets with peer credential validation.

## System tools

Browser, filesystem, terminal, network, device, notification, search, and
automation capabilities are tools rather than ambient agent powers. Their
manifests declare input/output schemas, risk, sandbox profile, and permissions.

- Browser uses WebDriver/BiDi through an isolated browser profile.
- Filesystem uses portal-style grants and canonical-path checks.
- Terminal executes argv arrays in transient systemd scopes; no shell parsing.
- Network uses destination and protocol allowlists.
- Device access uses portals and udev-backed typed operations.
- Notifications use the desktop notification D-Bus API.
- Search indexes explicitly granted local roots and permitted remote sources.
- Automation persists schedules and re-evaluates policy at execution time.

## Agent catalog

System, Terminal, File, Browser, Cloud, Kubernetes, Git, DataOps, Security, and
Research agents ship as signed manifests. They are compositions of granted
tools and prompts, not privileged binaries. Administrators may disable,
replace, or constrain every built-in agent.

## Gateway routing

Routing policy considers required capabilities, data classification, locality,
latency SLO, price ceiling, tenant allowlist, health, and quota. A request that
cannot satisfy all hard constraints fails closed. Provider adapters normalize
streaming, tool calls, usage, errors, and cancellation into one contract.

Credential material is referenced by opaque secret IDs. It is never placed in
agent prompts, task records, or audit payloads.

The implemented gateway follows the Hermes provider methodology without
embedding Hermes itself:

- callers select a canonical `provider:model` route
- provider identity is separate from the wire transport
- OpenAI-compatible and Anthropic Messages transports normalize to one response
- ordered fallback routes are filtered by capability, locality, credentials,
  data policy, and circuit health
- retryable rate-limit, timeout, and server failures use bounded backoff
- custom providers are declared in `/etc/agentos/providers.json`

The current milestone intentionally rejects streaming rather than buffering or
misrepresenting it. Streaming, Responses API, OAuth provider flows, secret
service integration, and per-provider model catalogs remain required before a
production release.

## Memory lifecycle

Session memory expires with its configured retention. Durable memory requires a
policy decision and records provenance, owner, sensitivity, and expiration.
Vector entries point to canonical records; embeddings are replaceable indexes,
not the source of truth. Knowledge graph edges retain source and confidence.
Deletion removes source records and asynchronously rebuilds derived indexes.
