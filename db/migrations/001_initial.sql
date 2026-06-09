PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    manifest JSON NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    goal_id TEXT REFERENCES goals(id),
    actor_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    resource TEXT NOT NULL,
    arguments JSON NOT NULL,
    arguments_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    risk TEXT NOT NULL,
    state TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(id),
    approver_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    scope JSON NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content JSON NOT NULL,
    provenance JSON NOT NULL,
    classification TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_edges (
    source_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    target_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    confidence REAL NOT NULL,
    provenance JSON NOT NULL,
    PRIMARY KEY (source_id, predicate, target_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    data JSON NOT NULL,
    previous_hash TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_actions_goal_state ON actions(goal_id, state);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_events(tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_memories_owner_kind ON memories(owner_id, kind);
