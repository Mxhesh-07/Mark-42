# ADRs

Short records of the decisions that are expensive to reverse. Newest last.

| # | Decision |
|---|----------|
| [0001](0001-fail-closed-permission-gate.md) | Every tool call goes through one fail-closed permission gate |
| [0002](0002-config-is-not-committed.md) | Credentials and machine state are never committed |
| [0003](0003-tamper-evident-audit-log.md) | The audit log is append-only and hash-chained |
| [0004](0004-sandbox-and-command-analysis.md) | File tools are sandboxed and shell commands are classified |
| [0005](0005-untrusted-content-breakers-and-structured-logs.md) | Fetched content is data, providers get breakers, logs are structured |
| [0006](0006-signed-approvals-egress-roles-and-subprocess-sandbox.md) | Approvals are signed, egress is checked, voices carry roles, code runs sandboxed |
| [0007](0007-graceful-degradation-and-observability.md) | The assistant degrades gracefully and explains itself |
| [0008](0008-transactional-memory-and-backup.md) | Memory is one transactional store, and the runtime state can be exported |
