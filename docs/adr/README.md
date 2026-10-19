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
| [0009](0009-one-door-for-portaudio.md) | PortAudio is created through one serialized door |
| [0010](0010-operating-prompt-v2-and-self-model.md) | The prompt states initiative/opinion/self-report, and the assistant models itself |
| [0011](0011-risk-scoring-and-pushback.md) | Risk is scored and a concern is raised at most once per effect |
| [0012](0012-proactivity-with-fixed-urgency.md) | Proactivity is capped by fixed urgency, budgets and quiet hours |
| [0013](0013-confirmation-modal-and-narrow-rules.md) | A confirmation is answered in the UI, and "always allow" is narrow |
| [0014](0014-devices-reach-last.md) | Devices is reach, and reach is the last thing to add |
| [0015](0015-tool-contract.md) | A tool is declared, dispatched and registered, or it is not a tool |
| [0016](0016-redaction-two-levels.md) | Redaction has two levels, and outbound text gets the smaller one |
