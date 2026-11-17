# NEXUS // MAINFRAME HUD

Portrait (9:16) sci-fi mainframe HUD. Vanilla HTML + CSS + JS, zero dependencies, no build step.

```
hud_web/
├── index.html   ← structure (inline SVG for all linework)
├── styles.css   ← design tokens, layout, glow, keyframes
└── hud.js       ← boot sequencer + live animation drivers
```

## Run

Double-click `index.html`. (Fonts load from Google Fonts; offline it falls back to Courier New.)

## The four tuning knobs

**1. Boot timing** — `hud.js`, top of file:

```js
var TIMING = {
  power:    500,   // chip + inner ring flicker on
  routing:  1000,  // circuit traces draw outward
  modules:  2000,  // panels blink online, staggered
  complete: 3800   // packets start flowing, caption fades
};
```

Per-panel stagger = `data-boot` index × 70ms + random jitter (see `data-boot` in `index.html`).
Lower the `70` in `hud.js` → `order * 70` to make the modules snap in faster.

**2. Layout** — `styles.css`, each panel is one line of percentages:

```css
.eq-mod   { left: 3.5%; width: 44%;   top: 14.6%; height: 16.5%; }
.chip-mod { right: 3.5%; width: 38%;  top: 14.6%; height: 16.5%; }
.hub      { left: 50%; top: 47.5%; width: 78%; aspect-ratio: 1/1; }
```

`left/right/top/height` are % of the stage, so everything scales as one unit.
The stage itself is locked to 9:16 and always fits the viewport.

**3. Units** — `--u` and `--v` are written by `hud.js` as 1% of the stage's
rendered width / height. Every size is `calc(var(--u) * N)`, so the whole
design is proportionally resizable. Change the type scale in one place:

```css
--fs-micro: calc(var(--u) * 1.30);
--fs-sm:    calc(var(--u) * 1.55);
--fs:       calc(var(--u) * 1.80);
```

**4. Colour + glow** — `:root` and `.stage`:

```css
--cyan: #00ffff;  --blue: #0077ff;  --white: #ffffff;  --amber: #ffa500;
```

For a different accent, change `--cyan` only; `--amber` is reserved for
warnings / buffering / ticker tag.

## Structure

| Region | Element | Notes |
|---|---|---|
| Status strip | `.topbar` | UTC + uptime, live via JS |
| Title | `.titleblock` | J.A.R.V.I.S, build meta |
| Centre | `.hub` | 9 concentric SVG rings, 4 rotating (CSS), microchip core |
| Top-left | `.eq-mod` | 18-bar analyser (JS driven) + 6 pill nodes |
| Top-right | `.chip-mod` | "9" block, 2 arc gauges, vertical BUFFERING |
| Sides | `.rail-a` / `.rail-b` | power alloc, subsystems, radar, signal strip |
| Bottom | `.pad-a/.pad-b` | 6×4 keypad matrices, random cells blink |
| Bottom | `.data-top/.wave-mod/.data-bot` | memory bank, live waveform, bus telemetry |
| Footer | `.ticker`, `.footer` | scrolling marquee + status chips |

## Circuits

`index.html` → `.circuits` SVG, `viewBox="0 0 900 1600"`, hub origin at `450,768`.

* `.traces-dim` — always-on faint underlay.
* `.traces-live` — same paths again, each with `pathLength="100"` so
  `stroke-dasharray:100 → stroke-dashoffset:0` draws them without measuring.
  `--i` sets the per-path delay.
* `.nodes` — terminal squares at each endpoint.
* `.packets` — SMIL `animateMotion` dots riding trunks `#t1 #t4 #t6 #t7`.

To add a trace: copy a `<path>` into both groups, give it `pathLength="100"`
and a unique `style="--i:N"`, then add a matching `<circle class="node">`.

## Boot state machine

`hud.js` adds classes to `.stage`; CSS does the rest.

| Class | Effect |
|---|---|
| *(none)* | pure black |
| `.powered` | chip + core bloom + frame appear (flicker keyframe) |
| `.routing` | traces draw, rings fade in with staggered delays |
| `.live` (per panel) | panel fades/slides in |
| `.complete` | data packets visible, boot caption fades out |

`prefers-reduced-motion` is already wired: rotation, marquee, sweeps and the
boot animations all resolve to their end state when it is requested.

## Accessibility / robustness

* `<noscript>` reveals all panels if JS is unavailable.
* No external JS, no fetch, no localStorage — works from `file://`.
* No layout thrash: animations use `transform`, `opacity` or `height` on
  small elements only.
