# MK-LXXXV — cinematic red flight HUD

A full-bleed, landscape **Iron Man / JARVIS** style heads-up display in crimson `#E60000`,
white `#FFFFFF`, amber `#FF8C00` and steel `#555555` on pitch black. Built for a desktop
canvas (**designed at 1536×960, 16:10**), not a phone.

It runs two ways:

* **live** — served by a tiny local bridge (`telemetry.py`) that feeds it real CPU / memory /
  GPU / disk / network values;
* **simulated** — opened straight off disk with no bridge, where it falls back to a
  clearly-labelled animation so the board still looks alive.

Sibling to `../hud_web/` (the cyan NEXUS mainframe HUD). Both live side by side in this repo
and share nothing but the visual language.

---

## Run it

### Live (recommended)

```powershell
python hud_mk85/telemetry.py --open
```

That starts a loopback-only server on `http://127.0.0.1:8787/`, serves the HUD itself, and
opens it as an app window. Then leave it running; the page polls once a second.

Or start the bridge and point a browser at the URL yourself:

```powershell
python hud_mk85/telemetry.py          # prints the URL
```

As a borderless window at the design size:

```powershell
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList `
  "--app=http://127.0.0.1:8787/", "--window-size=1536,960", "--new-window"
```

### Simulated

Just open `index.html`. The fetch fails, the strip reads `SIMULATION`, and every panel shows
plausible synthetic motion. Nothing breaks.

### Inside the assistant

`python main.py` starts this bridge **in-process** and opens the board itself as a Chrome/Edge
app window at 1536×960, so JARVIS speaks into a HUD instead of a chat window. The Tk window is
still there (hidden) and still owns typed input, confirmation dialogs and the tray icon — pull
it back with the tray icon when you need it.

* `--no-hud` (or `JARVIS_HUD=0`) runs the native window only.
* If the bridge cannot bind or no browser is found, the native window comes back by itself —
  the HUD is never the only way to reach the assistant.
* Closing the HUD window leaves the assistant running; `Stop-Process` on the python process,
  or the tray menu, ends it.

While it runs, the assistant also publishes voice state to `/state`, which is what drives the
subtitle line, the VOICE meter and the reactor bloom.

Append `?verify=1` to any URL to freeze the intro animations and pin every panel to full
opacity — that is what all the geometry/pixel checks below use, so screenshots are
deterministic. `?persona=friday` (or `ultron`) opens straight into that palette.

The only external request is `fonts.googleapis.com` for *Roboto Condensed* and *Share Tech
Mono*; both have local fallbacks (`Arial Narrow`, `Consolas`) so the page still reads offline.

---

## What is actually live

| Element | Real source |
|---|---|
| `SUIT` / `FLIGHT` / `WEAPON` wedge gauges + % | CPU, GPU and memory load (click a wedge to chart it) |
| Outer 27-bar radial chart | history of the selected metric (last 27 s) |
| `GPU TEMP` gauge | `nvidia-smi`, tagged **GPU** when measured |
| `CORE TEMP` gauge | no Windows sensor without admin → derived from CPU load, tagged **EST** |
| `AUXILIARY FAN` / `CPU FAN` | `N/A` unless a sensor is available (honest, not invented) |
| `DOWNLOAD` / `UPLOAD` graphs | real `psutil.net_io_counters` deltas, kB/s (MB/s when large) |
| `DISK STATUS` bars | real volume usage; row 2 is the next volume or an `ALL` aggregate |
| `USB STORAGE INFO.` | actual removable volumes (says `NO MEDIA` when there are none) |
| `PROXIMITY` scope | established TCP connections + inbound/outbound rates |
| Telemetry rail (7 rows) | CPU, memory, GPU, storage, net I/O, process count, battery |
| Bottom deck | core clock (GHz), GPU temp, uptime, free RAM |
| Clock | real local time, re-synced to the minute boundary |

Anything the machine cannot measure is rendered as `--`, `N/A` or with an `EST` tag — never
passed off as a reading. That distinction is the point: a HUD that lies is worse than one
that says "no sensor".

### The bridge

`hud_mk85/telemetry.py` — standard library + `psutil` (already pinned). No new dependencies.

```
GET /            the HUD (same origin, so no CORS games needed)
GET /telemetry   one JSON snapshot
GET /state       the assistant's voice state (read-only, see below)
GET /health      {"ok": true}
```

* Binds `127.0.0.1` only, read-only, serves nothing outside `hud_mk85/`.
* Two background threads: a 1 s fast loop (CPU, memory, network, uptime) and a 5 s slow loop
  (`nvidia-smi`, disk usage, process scan, connection count). Requests only ever read a
  cached snapshot, so a slow sensor probe cannot stall the page.
* `Access-Control-Allow-Origin: *` on `/telemetry`, so a `file://` copy of the HUD can still
  reach a running bridge.
* `/state` is deliberately **not writable**: no POST/PUT/DELETE handler exists, so a random
  web page cannot push text into the HUD. Only the assistant process updates it, in memory.

```jsonc
// GET /state
{
  "status":  "IDLE",        // OFFLINE | IDLE | LISTEN | THINK | SPEAK
  "mic":     0.03,          // 0..1 microphone level
  "speaking": false,
  "thinking": false,
  "you":     "run a diagnostic",       // your last turn, as heard
  "jarvis":  "All systems nominal.",   // the reply, streamed
  "turn":    7,
  "persona": "jarvis",      // jarvis | friday | ultron  -> the palette
  "ts":      1761500000.12
}
```

The page polls it at ~8 Hz with endpoint rotation (falls back between `/state` and
`/telemetry` if one is unreachable), and shows `OFFLINE` when nothing answers within 900 ms.
`LISTEN` is not a separate signal from the assistant: it is simply "there is speech energy and
the assistant is neither thinking nor talking".

---

## Protocols — JARVIS / FRIDAY / ULTRON

The board ships with three palettes. Switching one is a **morph**, not a hard swap:

| Protocol | Palette | Rings | Key |
|---|---|---|---|
| **J.A.R.V.I.S** | crimson `#e60000` + white | 82 s / 46 s | `1` |
| **F.R.I.D.A.Y** | amber `#ff9900` + gold | ~25% quicker | `2` |
| **U.L.T.R.O.N** | hard red `#ff002b`, no warmth | ~45% quicker, jolts in | `3` |

Three ways to change it:

1. **Click the name** in the top strip (or focus it and press Enter) — cycles the three.
2. **Press `1` / `2` / `3`** anywhere on the board.
3. **Say it** — *"switch to FRIDAY"*. The assistant calls `switch_persona`, which publishes
   `persona` on `/state`; the page picks the change up on its next poll.

The shift itself: the palette is defined as **registered CSS custom properties**
(`@property --red { syntax: '<color>' }`), so changing the persona *interpolates* every colour
over `--morph` (0.95 s) instead of snapping — including the SVG gradient ramps, which are
repointed at the same variables in CSS because presentation attributes cannot hold `var()`.
While that happens a sweep overlay with the new name plays, and the ring stack changes tempo.

The choice is remembered in `localStorage`, so the board comes back as you left it.

**It is cosmetic.** The palette changes; the assistant's prompt, voice and behaviour do not.
The tool's own description says so, and it returns "HUD protocol switched to FRIDAY" — it must
not claim a personality change.

---

## The board

```
┌ TOP STRIP ──────────── TELEMETRY LINK / JARVIS / GPU NAME ─────────────┐
│                                                                        │
│   ╲ SYSTEM DIAGNOSTICS                     ┌ PROXIMITY ┐   ║ TELEMETRY │
│    ╲  ┌─────┐  ╔═══════════════════════╗   └──────────┘   ║   RAIL    │
│     ╲ │bust │  ║      HUB (66vh)       ║                  ║  (7 rows) │
│      ╲│     │  ║   /───────────────\   ║                  ║  + EQ     │
│       ╲ GPU ║  ║  /  SUIT  │ FLIGHT \  ║                  ║           │
│        ╲TEMP║  ║ │   WEAPON  ·  23:22 │ ║                  ║           │
│         ╲   ║  ║  \   ring ticks,    /  ║                  ║           │
│   DISK   ╲  ║  ║   \  radial bars  /    ║   ╱ USB STORAGE INFO.       │
│   STATUS  ╲ ║  ║    \─────────────/     ║  ╱   E: F: G:  ▮▮▮▮ 100%     │
│  (55%/48%) ╲╚═══════════════════════════╝ ╱   (isometric drive art)   │
│                                                                        │
└ BOTTOM DECK ──────────────────────────────────────────────────────────┘
```

### Central hub

* Three concentric ring groups plus a hairline outer ring; each group rotates
  independently, alternating direction, at different speeds.
* **Inner core** is split into three dark wedges labelled `FLIGHT`, `SUIT`, `WEAPON`,
  each carrying a live arc gauge at its outer edge and a percentage beneath the label.
  Hovering highlights a wedge; clicking it switches the radial chart to that metric.
* **Arc reactor** in the centre: segmented iris, rotating triangular core, and a bloom whose
  intensity follows CPU load.
* **Digital clock** at 12 o'clock inside a bordered box, `HH:MM`, real local time,
  re-synced to the minute boundary, with a one-pixel red ghost for the chromatic split
  movie HUDs have.
* **Mid rings** carry tick marks built from `stroke-dasharray` (348 of them, generated
  in `app.js`).
* **Outer radial bar chart** on the right: 27 bars sweeping ~120°, alternating tall red
  and short white. Heights are the selected metric's history: a fully loaded metric reaches
  the designed 86-unit bar, idle still reads 42 so the silhouette never collapses.
* A faint hex mesh sits behind the rings (Mark-series armour cue) with instrument
  micro-labels scattered along the ring field.

### Panels (each is a rotated `position:absolute` card)

| Panel | Content | Tilt |
|---|---|---|
| `SYSTEM DIAGNOSTICS` | SVG wireframe bust, curved `GPU TEMP` / `CORE TEMP` gauges (orange → red) with `GPU`/`EST` provenance tags, `AUXILIARY FAN` / `CPU FAN`, block graphs for `DOWNLOAD` / `UPLOAD` | −30° |
| `DISK STATUS` | Two real volumes as segmented orange bars, circular targeting dial whose needle tracks the busiest volume, angled tab with free space + volume count | −60° |
| `USB STORAGE INFO.` | Isometric multi-part USB plug in silver/grey, up to three removable drives with red segmented bars; dims to `NO MEDIA` when nothing is plugged in | +30° |
| `PROXIMITY` | Radar scope whose sweep speed and hot blips follow real network traffic | +30° |

Plus the non-spec furniture that turns a ring into a *board*: top status strip, a vertical
trunk line dropping from the strip into the clock, leader lines from the hub to each panel
header, the right telemetry rail (7 rows + a bar equaliser), the bottom deck, corner
brackets, a faint radial grid, scanlines, a slow diagonal sweep and a vignette.

---

## Tuning it

Everything is CSS variables — no build, no JS constants to hunt for.

**Palette / scale** — top of `styles.css`:

```css
:root {
  --bg: #000000; --white: #ffffff;
  --red: #e60000; --red-2: #ff2d2d;
  --amber: #ff8c00; --steel: #555555;
  --s: 1vmin;   /* master scale unit: every size is a multiple of this */
}
```

The whole palette is those seven colour tokens (the three protocol skins below override them),
so recolouring the board is a one-block edit — nothing is hardcoded downstream except the
neutral greys and white.

**Panel position** — the layout table in the header comment of `styles.css`, and the
matching rules next to each panel:

```css
.panel--diag { --x: 22%;   --y: 35.5%; --w: 42; --h: 32; --tilt: -30deg; }
.panel--disk { --x: 15%;   --y: 77%;   --w: 26; --h: 32; --tilt: -60deg; }
.panel--usb  { --x: 82.5%; --y: 71%;   --w: 44; --h: 28; --tilt:  30deg; }
.panel--aux  { --x: 78.5%; --y: 35%;   --w: 22; --h: 15; --tilt:  30deg; }
```

`--x/--y` are the **centre** of the panel (percent of the viewport), `--w/--h` are in `--s`
units, `--tilt` rotates the whole card. Because the panels are rotated, changing one number
can collide with a neighbour — the solved values above are collision-free at 1536×960
(verified with a separating-axis test; see *Checks* below).

**Hub size**: `.hub { width/height: 66vh }`. The SVG is a fixed `1000×1000` viewBox, so at
1536×960 one SVG unit = 0.634 px.

**Polling / effects**: `CFG` at the top of `app.js` holds the clock interval, the poll period
and graph bar count. Motion timings live in `styles.css` keyframes.

### Adaptive fallbacks

| Breakpoint | Behaviour |
|---|---|
| aspect ≤ 3:2 | hub 56vh, panels shrink and pull in, `.rail` / `.panel--aux` / `.deck` hidden |
| aspect ≤ 1:1 | hub 52vh, panels stack centre-left / centre-right, top-strip centre hidden |
| aspect ≥ 21:9 | deck widens |
| height ≤ 620px | top strip hidden |
| `prefers-reduced-motion` | all animation disabled, parallax off |

So it degrades to a sensible 3-panel layout on 4:3 or portrait screens rather than
overlapping itself — but the intended canvas is 16:10 landscape.

---

## Files

| File | What |
|---|---|
| `index.html` | markup: hub SVG (rings, wedges, reactor, clock, labels), 4 panels, rail, deck, trunk, boot overlay, protocol-shift overlay |
| `styles.css` | tokens + registered palette properties, three protocol skins, layout vars, rotations, all keyframes, adaptive fallbacks |
| `app.js` | SVG builders, telemetry client + bindings, segmented bars, block graphs, clock, boot, callouts, parallax, persona switch |
| `telemetry.py` | loopback HTTP bridge: real system snapshot as JSON, serves the HUD |
| `_diag.js` | dev harness: dumps geometry (offset w/h, computed rotation, centre), text clipping, overflow and element counts as JSON into the DOM |
| `_diag.html` | throwaway copy of `index.html` with the harness appended — **regenerate after editing `index.html`** |

Regenerate the harness (Python, not PowerShell: `Set-Content -Encoding UTF8` adds a BOM and
`Get-Content` can mangle multi-byte characters):

```python
import io
src = io.open('index.html', encoding='utf-8').read()
catcher = ('<script>window.__errors=[];'
           'window.addEventListener("error",e=>window.__errors.push(String(e.message)));'
           '</script>')
src = src.replace('<script src="app.js"></script>', catcher + '<script src="app.js"></script>')
src = src.replace('</body>', '<script src="_diag.js"></script></body>')
io.open('_diag.html', 'w', encoding='utf-8', newline='\n').write(src)
```

Read it headlessly at a true 1536×960 viewport (headless Chrome reports a smaller window than
requested, so over-request by the chrome height):

```powershell
& chrome --headless=new --window-size=1554,1112 --virtual-time-budget=8000 `
    --dump-dom "http://127.0.0.1:8787/_diag.html?verify=1"
```

For anything involving the live fetch, use Playwright instead of `--dump-dom`:
`--virtual-time-budget` fast-forwards timers while the real HTTP request is still in flight,
so the page is dumped before the first snapshot lands.

### Checks performed on this build (1536×960)

* 4 panels, 0 separating-axis intersections between any two of them; 0 with the deck,
  rail or top strip; every rotated corner on-screen.
* No horizontal overflow, no vertically clipped text, nothing rendered off-stage.
* Element counts: 4 panels, 110 segmented-bar cells, 52 graph bars, 27 hub bars, 348 ticks,
  12 reactor iris segments, 3 segment gauges, 4 leader lines, 5 radar blips.
* Live binding confirmed against the running bridge: CPU/memory/GPU/disk/net/uptime/battery
  all populated, `GPU TEMP` tagged `GPU` (measured) and `CORE TEMP` tagged `EST` (derived),
  no console errors and no failed requests.
* Wedge click switches the charted metric; panel hover raises brightness.
* Pixel audit of a headless screenshot: max luma 255, ~10.6% of the frame non-black, red /
  amber / white ink present in every expected region.
* Protocols, verified in-browser at 1536×960: the palette variables resolve per skin
  (`--red` → `rgb(230,0,0)` / `rgb(255,153,0)` / `rgb(255,0,43)`), the `#gRed` gradient stop
  follows the same value, ring tempo changes with it, the shift overlay plays, keys `1`/`2`/`3`
  and a click on the top-strip name both work, and the choice survives a reload.
* Remote control of the palette verified against the real bridge: publishing
  `persona=friday` on `/state` morphs the board, a local click is *not* reverted by the next
  130 ms poll, and a later backend value still wins.

---

## Notes / trade-offs

* **No JS framework, no bundler** — three files plus one Python script.
* Filters (`blur`/glow) are applied to rings and text only. The 27 radial bars are left
  unfiltered on purpose: filtering them costs frames for no visible gain at this size.
* Fonts come from Google Fonts; the layout does not depend on them (fallback metrics are
  close, and no text is clipped in the audited viewport).
* CPU temperature and fan speeds need a sensor service (LibreHardwareMonitor) or elevation
  on Windows; without one they are labelled `EST` or `N/A` rather than invented.
* `?verify=1` disables the intro reveal, the boot overlay and the parallax so screenshots are
  reproducible.

MIT, like the rest of the repo.
