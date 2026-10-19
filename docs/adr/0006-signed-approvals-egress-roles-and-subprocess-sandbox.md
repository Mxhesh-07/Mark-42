# 0006 — Approvals are signed, egress is checked, voices carry roles, code runs sandboxed

**Status:** accepted

## Context

The gate (0001) decided *whether* a tool could run, but four holes remained around it:

- A confirmation was a bare yes/no in-process. The background agent can be running
  unattended, so "approved" had to mean something stronger than a boolean that a bug — or a
  prompt-injected instruction — could set.
- Tools that take a URL or host (`browser_control`, `web_search`, `send_message`,
  `flight_finder`, …) could be pointed anywhere, including at the user's own machine or
  router.
- Anyone who could speak to the microphone could drive the assistant; there was no notion
  of *who* was asking.
- Tools that run model-generated code executed it in the assistant's own process, with the
  assistant's environment and API keys.

## Decision

**Approvals are signed, single-use and bound to the effect (A1).** `agent/approval.py`
builds a manifest that describes the *effect* ("delete C:\x\y.txt (2.1 MB)"), not the tool
name, and a token `expires_ms.nonce.hmac_sha256` over the tool plus a digest of the full
arguments. `authorize()` verifies the signature, the expiry and the replay store before
returning; the nonce is then consumed, so a token authorises exactly one invocation. The
expiry field is integer **milliseconds** on purpose: a float would contain a `.`, which is
also the token's field separator. The HMAC key is `JARVIS_APPROVAL_KEY` if set, else a
64-hex-character key generated on first use at `memory/approval.key` (gitignored).

**Egress is checked (A4).** `agent/egress.py` extracts the destination a tool names, checks
`egress.allow` / `egress.deny` and, by default, refuses private and loopback addresses so a
fetched instruction cannot make the assistant call the user's own services. A deliberate
local service (e.g. Ollama on `localhost:11434`) is added to `egress.allow`.

**A voice is an authority (A8).** `agent/roles.py` maps an enrolled speaker to `owner` or
`guest` and caps a non-owner at read-only actions. `enforce_on_unknown` defaults to
**false**, so enabling roles cannot lock the owner out before their voice is enrolled; a
recognised-but-uncharted voice is the configured default (`owner`) — *enrolment is
authorisation*. Non-owner blocks are `hard`, so they can never be widened by attendance.

**Generated code runs in a sandboxed subprocess (A11).**
`agent/subprocess_sandbox.py` runs a Python file in a child process with a restricted
environment (secret-shaped variables stripped), a temporary working directory, and — on
Windows — memory and CPU limits via a Job Object.

**The live path is gated too.** The background agent already went through `policy.evaluate`;
the live voice path did not. `main.py::_execute_tool` now calls `policy.evaluate_live()`,
which treats an *attended* request as authorisation for a soft `confirm` or a soft
policy-table `block`. `Decision.hard` marks the blocks that attendance cannot lift: the kill
switch, a sandbox escape, a refused shell command, a denied destination, a rate-limit guard
and a non-owner speaker.

## Consequences

- A bug, a replay or a tampered token cannot turn a former "yes" into an authorisation.
- An unattended run that needs a confirmation fails closed (`approver=None` refuses).
- Egress defaults are safe; a blocked legitimate destination produces a clear reason and is
  one config line to allow.
- With roles enforced, a guest can read but not write, message or run shell — and cannot
  talk their way past it.
- The sandbox side effect is real: with `sandbox.roots: ["~"]`, any path outside the home
  directory is blocked until another root is added.
