# The HUD shell (Tier 3)

Everything here is optional: the voice loop works without touching the UI. The
shell exists because a terminal transcript is a poor place to watch a long task
and a worse place to approve a risky one.

## Keyboard

| Key | Action |
| --- | --- |
| `Ctrl+K` | Floating text composer (voice-first, not voice-only) |
| `Ctrl+H` | Transcript viewer: search, export `.txt` / `.json` |
| `Ctrl+C` | Copy the selection from the log or thinking pane |
| `Esc` | Close the topmost transient window (settings, transcript, composer) |
| `F6` | Notification digest in the thinking pane |
| `F7` | Settings |
| `F8` | Recent audit entries |
| `F9` | Engage the kill switch |
| `F10` | Screenshot mode (hides chrome for README/demo captures) |
| `F11` | Debug overlay: tick, queues, mic level, provider state |
| `Ctrl+Shift+T` | Toggle always-on-top |
| `Ctrl+Shift+M` | Minimise |

The text composer sends through exactly the same path as a voice turn, so a
typed command is subject to the same permission gate and audit log.

## Panes

- **Status strip** — provider/model, fallback state, queue depth, mode. Refreshed
  every five seconds, never on the animation tick.
- **Thinking pane** — tool calls, arguments, results, audit lines, notifications.
  Text is selectable; `Ctrl+C` copies.
- **Log pane** — running transcript. The same rows feed the transcript viewer.
- **Task/memory/agent panels** — the current plan, what is remembered locally and
  per-agent state. Tooltips explain the abbreviations.

## Settings

Theme (Arc Blue, Warm Amber, Mono, High-Contrast), audio cues (off by default),
kill switch, hologram launch/close, and a read-only status block. The dialog
never displays a credential.

`font_scale` in `config/ui.json` enlarges every HUD font at once (0.8–2.0).

## Hologram

The projector is a separate pygame window, never a browser. The settings dialog
lists the built-in models and can launch or close it; the HUD reports
`hologram: running/idle` in the status line. If pygame is missing the control
still opens and reports `unavailable`.

## Accessibility and degradation

- Every action above is reachable from the keyboard.
- State is shown with a symbol as well as colour (`✓`, `⟳`, `◈`, `⊘`).
- A missing optional dependency (pygame, win10toast, webrtcvad) degrades to a
  status line, not an exception in the paint loop.
- The animation loop drops to ~4 fps when the window is iconified; the memory
  panel reads from disk on a worker thread, so a slow disk cannot freeze the HUD.
- A drawn boot splash is shown for under a second and can fail silently.

## Layout

`ui/layout_spec.py` is the single source for the main pane geometry; window
position/size persists in `config/ui.json` and is clamped to the monitor in use.
