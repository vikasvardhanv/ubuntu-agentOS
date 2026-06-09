# Installation and First Boot

## Image construction

AgentOS images are produced from signed Ubuntu 24.04 LTS packages using
reproducible build manifests. AgentOS packages add services and a GNOME session
without replacing the Ubuntu kernel. Secure Boot remains enabled. Updates use
signed APT repositories, phased rollout, health checks, and rollback.

## Installation

The installer uses the Ubuntu installer stack and supports encryption, TPM
enrollment, enterprise identity, recovery keys, and offline installation.
Agent services remain disabled until first-boot configuration succeeds.

## First boot

1. Create or join a user identity and configure disk/recovery options.
2. Select local-only, managed enterprise, or custom deployment mode.
3. Configure model providers using secret references; Ollama/local is optional.
4. Configure memory retention, encryption, indexing roots, and remote sync.
5. Review baseline permissions and approval policy.
6. Run diagnostics, create the initial signed configuration, and start runtime.
7. Present a guided, approval-visible first goal.

Interrupted onboarding resumes transactionally. Provider setup can be skipped;
the desktop remains usable as standard Ubuntu.
