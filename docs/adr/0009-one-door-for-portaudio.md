# 0009 — PortAudio is created through one serialized door

**Status:** accepted (2026-10-20)

## Context

The startup self-check runs on a background thread so it cannot delay the
window. It probed the microphone, which means calling `pyaudio.PyAudio()`.

`main.py` also builds a module-level `pyaudio.PyAudio()` while it is being
imported. Two threads inside PortAudio's global initialisation at the same time
does not raise — on Windows it kills the process with an access violation
(`0xC0000005`). Reproduced consistently:

```
python -c "import main"        # exit=-1073741819
```

Stubbing either the self-check or the mic probe made the crash disappear, and
`import main` was stable 3/3 with `check_mic` replaced by a stub.

## Decision

1. Every PyAudio instance in the project is created through
   `agent.audio.open_pyaudio()`, which serializes construction behind one
   process-wide lock. The lock is held only for construction, never for a
   stream's lifetime, so a long recording cannot block a probe.
   `agent.audio.close()` terminates an instance and is safe on `None` and on a
   failing `terminate()`.
2. The microphone probe is **not** part of the startup self-check. It is the
   only check that initialises a C library, so it runs on demand instead:
   `python -m agent.health --full`, or `GET /health?full=1` while the app is
   alive.

## Consequences

- `import main` is stable, and the startup self-check reports in ~300 ms.
- A running app can answer a readiness probe without racing its own audio.
- A genuinely broken microphone is no longer reported at boot; it surfaces on
  the first listen (and on request via the health endpoint). That is an
  acceptable trade for removing a hard-crash class.
- `agent/health.checks(full=True)` still includes the mic probe by default, so
  existing callers and the one-shot CLI keep their behaviour; only the
  in-process startup caller passes `audio=False`.
