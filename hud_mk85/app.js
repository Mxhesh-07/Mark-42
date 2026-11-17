/* ============================================================================
   MK-LXXXV FLIGHT HUD - behaviour
   ----------------------------------------------------------------------------
   1. SVG builders      tick rings, radial history chart, segment gauges,
                        reactor iris, instrument micro-labels
   2. Meters            segmented bars, block graphs
   3. Telemetry         reads /telemetry (hud_mk85/telemetry.py) once a second;
                        falls back to a clearly-labelled simulation when the
                        bridge is not running, so the board still lives
   4. Binding           each panel is a view over the snapshot
   5. Effects           boot sequence, leader-line callouts, parallax, decode
   Timings live in CFG.
   ========================================================================== */
(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const VERIFY = params.has('verify');
  if (VERIFY) document.documentElement.classList.add('verify');

  /* -- config --------------------------------------------------------------- */
  const CFG = {
    clock: { updateMs: 60_000 },
    poll:  { everyMs: 1000, timeoutMs: 1800 },
    voice: { everyMs: 130, timeoutMs: 900 },
    graph: { bars: 26, tickMs: 140 },
    // Where the bridge listens. Same-origin when the page is served by it;
    // the absolute fallback lets a file:// page still reach a running bridge.
    endpoints: [
      'telemetry',
      'http://127.0.0.1:8787/telemetry',
    ],
    voiceEndpoints: [
      'state',
      'http://127.0.0.1:8787/state',
    ],
  };

  const NS = 'http://www.w3.org/2000/svg';
  const CX = 500, CY = 500;
  const HIST = 27;                       // radial chart bar count
  const METRICS = ['cpu', 'mem', 'gpu'];

  /* -- helpers -------------------------------------------------------------- */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const num = (v, d = 0) => (typeof v === 'number' && isFinite(v) ? v : d);

  function mk(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  function polar(r, deg) {
    const a = (deg * Math.PI) / 180;
    return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
  }

  /** SVG arc path between two angles (degrees, y-down, clockwise). */
  function arcPath(r, a0, a1) {
    const a = polar(r, a0), b = polar(r, a1);
    const sweep = ((a1 - a0) % 360 + 360) % 360;
    const large = sweep > 180 ? 1 : 0;
    return `M${a.x.toFixed(2)} ${a.y.toFixed(2)} A${r} ${r} 0 ${large} 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
  }

  /* ==========================================================================
     1. HUB GEOMETRY
     ========================================================================== */

  function radialTicks(group, opts) {
    const { rIn, rOut, count, width, opacity, offset = 0, color = '#fff' } = opts;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
      const deg = offset + (i * 360) / count;
      const a = polar(rIn, deg);
      const b = polar(rOut, deg);
      frag.appendChild(mk('line', {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        stroke: color,
        'stroke-width': width,
        'stroke-opacity': opacity,
      }));
    }
    group.appendChild(frag);
  }

  function buildTicks() {
    const outer = $('#ticksOuter');
    const inner = $('#ticksInner');
    if (outer) {
      radialTicks(outer, { rIn: 466, rOut: 478, count: 180, width: 1.1, opacity: .30 });
      radialTicks(outer, { rIn: 458, rOut: 484, count: 60,  width: 2.2, opacity: .55 });
      radialTicks(outer, { rIn: 440, rOut: 446, count: 12,  width: 2.6, opacity: .9, color: '#e60000' });
    }
    if (inner) {
      radialTicks(inner, { rIn: 312, rOut: 324, count: 90, width: 1.1, opacity: .38 });
      radialTicks(inner, { rIn: 306, rOut: 330, count: 6,  width: 2.4, opacity: .75, color: '#e60000' });
    }
  }

  /* -- radial history chart -------------------------------------------------- */
  const hubBars = [];

  function buildHubBars() {
    const host = $('#hubBars');
    if (!host) return;

    const from = -54, to = 54, rim = 470, w = 7;
    for (let i = 0; i < HIST; i++) {
      const a = from + ((to - from) * i) / (HIST - 1);
      const isRed = i % 2 === 0;
      const rect = mk('rect', {
        x: CX - w / 2,
        y: CY - rim,
        width: w,
        height: 18,
        rx: 1,
        fill: isRed ? 'url(#gRed)' : 'url(#gWhite)',
        transform: `rotate(${90 + a} ${CX} ${CY})`,
        class: isRed ? 'hubbar hubbar--red' : 'hubbar hubbar--white',
      });
      rect.style.setProperty('--i', i);
      host.appendChild(rect);
      hubBars.push({ el: rect, red: isRed });
    }
  }

  /**
   * Height = the history value, but mapped onto the tall/short silhouette the
   * board was designed around: a fully loaded metric still reaches the original
   * 86-unit red bar, idle sits at 42 rather than collapsing to a stub.
   * White bars ride at 56% of their red partner.
   */
  function paintHubBars(series) {
    for (let i = 0; i < hubBars.length; i++) {
      const v = clamp(num(series[i], 0), 0, 100);
      const tall = 42 + (v / 100) * 44;
      const h = tall * (hubBars[i].red ? 1 : 0.56);
      hubBars[i].el.setAttribute('height', h.toFixed(1));
      hubBars[i].el.setAttribute('fill', hubBars[i].red ? 'url(#gRed)' : 'url(#gWhite)');
    }
  }

  /* -- core segment gauges --------------------------------------------------- */
  // Angular spans measured from the verified wedge paths.
  const SEGMENTS = {
    cpu: { a0: 213, a1: 327 },   // SUIT   (top)
    gpu: { a0: 333, a1: 447 },   // FLIGHT (right)
    mem: { a0: 93,  a1: 207 },   // WEAPON (left)
  };
  const segArcs = {};

  function buildCoreArcs() {
    const host = $('#coreArcs');
    if (!host) return;
    Object.entries(SEGMENTS).forEach(([key, { a0, a1 }]) => {
      const track = mk('path', {
        d: arcPath(250, a0, a1),
        class: 'segarc__track',
        pathLength: 100,
      });
      const fill = mk('path', {
        d: arcPath(250, a0, a1),
        class: 'segarc__fill',
        pathLength: 100,
        'data-metric': key,
      });
      host.appendChild(track);
      host.appendChild(fill);
      segArcs[key] = fill;
    });
  }

  function paintCoreArcs(values) {
    METRICS.forEach((k) => {
      const pct = clamp(num(values[k], 0), 0, 100);
      if (segArcs[k]) segArcs[k].style.strokeDashoffset = String(100 - pct);
    });
  }

  /* -- reactor iris ---------------------------------------------------------- */
  function buildReactor() {
    const host = $('#reactorIris');
    if (!host) return;
    const n = 12;
    for (let i = 0; i < n; i++) {
      const a0 = (i * 360) / n + 2;
      const a1 = ((i + 1) * 360) / n - 2;
      const outer = 96, inner = 62;
      const p1 = polar(outer, a0), p2 = polar(outer, a1);
      const p3 = polar(inner, a1), p4 = polar(inner, a0);
      host.appendChild(mk('path', {
        d: `M${p1.x.toFixed(1)} ${p1.y.toFixed(1)} A${outer} ${outer} 0 0 1 ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}` +
           ` L${p3.x.toFixed(1)} ${p3.y.toFixed(1)} A${inner} ${inner} 0 0 0 ${p4.x.toFixed(1)} ${p4.y.toFixed(1)} Z`,
        class: i % 3 === 0 ? 'iris__seg iris__seg--hot' : 'iris__seg',
      }));
    }
  }

  /* -- instrument micro-labels ----------------------------------------------- */
  function buildMicroLabels() {
    const host = $('#microLabels');
    if (!host) return;
    const items = [
      { r: 424, a: 152, t: '0x1F',  s: 8.5 },
      { r: 424, a: 208, t: 'PWR',   s: 8.5 },
      { r: 424, a: 332, t: 'NAV',   s: 8.5 },
      { r: 424, a: 28,  t: '0x2C',  s: 8.5 },
      { r: 358, a: 128, t: 'ARM.L', s: 8 },
      { r: 358, a: 232, t: 'ARM.R', s: 8 },
      { r: 358, a: 12,  t: 'SYNC',  s: 8 },
      { r: 358, a: 348, t: 'O2',    s: 8 },
    ];
    items.forEach((it) => {
      const p = polar(it.r, it.a);
      const t = mk('text', {
        x: p.x.toFixed(1), y: p.y.toFixed(1),
        class: 'micro__t', 'font-size': it.s,
        'text-anchor': 'middle',
      });
      t.textContent = it.t;
      host.appendChild(t);
    });
  }

  /* ==========================================================================
     2. METERS
     ========================================================================== */

  const SEG_BLOCKS = 22;

  function buildSegbar(el) {
    el.innerHTML = '';
    const pct = Number(el.dataset.pct || 0);
    const lit = Math.round((SEG_BLOCKS * pct) / 100);
    for (let i = 0; i < SEG_BLOCKS; i++) {
      const b = document.createElement('i');
      if (i < lit) b.className = 'on';
      b.style.setProperty('--i', i);
      el.appendChild(b);
    }
    el.dataset.pct = pct;
  }

  /** Update an existing segbar without rebuilding its blocks. */
  function setSegbar(el, pct) {
    if (!el) return;
    pct = clamp(pct, 0, 100);
    const lit = Math.round((SEG_BLOCKS * pct) / 100);
    const blocks = el.children;
    for (let i = 0; i < blocks.length; i++) {
      blocks[i].classList.toggle('on', i < lit);
    }
    el.dataset.pct = pct;
  }

  function buildGraph(host) {
    const bars = [];
    for (let i = 0; i < CFG.graph.bars; i++) {
      const cell = document.createElement('div');
      cell.className = 'gbar';
      const fill = document.createElement('i');
      cell.appendChild(fill);
      host.appendChild(cell);
      fill.style.setProperty('--h', '8%');
      bars.push({ fill, h: 8 });
    }
    return bars;
  }

  /** Feed one sample into a block graph (shifts left, appends right). */
  function pushGraph(bars, value) {
    const v = clamp(value, 4, 100);
    bars.shift();
    bars.push({ fill: null, h: v });
    // Re-link DOM to the shifted array.
    for (let i = 0; i < bars.length; i++) {
      if (!bars[i].fill) bars[i].fill = bars[i - 1] ? bars[i - 1].fill : null;
    }
    paintGraph(bars);
  }

  /** Simpler + cheaper: each bar eases toward the newest sample. */
  function paintGraph(bars, target) {
    const t = clamp(num(target, 8), 4, 100);
    for (let i = 0; i < bars.length; i++) {
      const bias = (i / bars.length) * 0.55;      // older bars lean lower
      const goal = clamp(t * (1 - bias) + 6, 3, 100);
      bars[i].h = lerp(bars[i].h, goal, 0.34);
      bars[i].fill.style.setProperty('--h', bars[i].h.toFixed(1) + '%');
    }
  }

  /* ==========================================================================
     3. TELEMETRY
     ========================================================================== */

  const STATE = {
    live: false,
    data: null,
    hist: { cpu: [], mem: [], gpu: [], net: [] },
    selected: 'cpu',
    shown: { cpu: 0, mem: 0, gpu: 0, net: 0, rx: 0, tx: 0 },
    sim: 0,
    fetchIndex: 0,
  };

  function logHist(key, value) {
    const h = STATE.hist[key];
    h.push(clamp(num(value, 0), 0, 100));
    while (h.length > HIST) h.shift();
    while (h.length < HIST) h.unshift(h[0] ?? 0);
  }

  /** A believable placeholder when the bridge is not running. */
  function simulate() {
    STATE.sim += 1;
    const t = STATE.sim;
    const wave = (a, b, c) => 40 + 18 * Math.sin(t * a) + 8 * Math.sin(t * b + c);
    const cpu = clamp(wave(0.11, 0.37, 0.4), 6, 92);
    const mem = clamp(58 + 6 * Math.sin(t * 0.07), 40, 88);
    const gpu = clamp(wave(0.06, 0.29, 2.1) * 0.8, 0, 88);
    return {
      ok: true, sim: true,
      cpu: { pct: cpu, per: [], cores: 8, threads: 16, freq: 2400 },
      mem: { pct: mem, used: 9.4, total: 16 },
      gpu: { name: 'SIMULATED', temp: 52 + 8 * Math.sin(t * 0.09), pct: gpu,
             mem_used: 1200, mem_total: 6144 },
      temps: { gpu: 52 + 8 * Math.sin(t * 0.09), cpu: null },
      fans: { aux: 2140, cpu: 1890 },
      disks: [{ letter: 'C:', pct: 55, total: 476, used: 262 }],
      usb: [], net: { rx: 60 + 40 * Math.abs(Math.sin(t * 0.3)), tx: 24 + 18 * Math.abs(Math.cos(t * 0.23)) },
      procs: 320, uptime: 86 * 3600, battery: { pct: 88, plugged: true },
      top: [], conns: 24, est: ['cpu_temp', 'fans'],
    };
  }

  async function fetchOnce() {
    const url = CFG.endpoints[STATE.fetchIndex % CFG.endpoints.length];
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), CFG.poll.timeoutMs);
    try {
      const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      if (!data || data.ok === false) throw new Error('no data');
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  async function poll() {
    try {
      const data = await fetchOnce();
      STATE.data = data;
      if (!STATE.live) {
        STATE.live = true;
        setMode('LIVE');
      }
      apply(data);
    } catch (e) {
      if (STATE.live) {
        STATE.live = false;
        setMode('SIM');
      }
      // rotate endpoint on failure so a file:// page can reach the bridge
      STATE.fetchIndex += 1;
      apply(simulate());
    }
  }

  /* ==========================================================================
     3b. VOICE LINK  (/state - written by main.py through the bridge)
     ========================================================================== */

  const VOICE = {
    on: false,
    status: 'OFFLINE',
    mic: 0,
    speaking: false,
    thinking: false,
    you: '',
    jarvis: '',
    turn: 0,
    remotePersona: '',
    idx: 0,
  };

  // Short enough to fit the rail's state column without squeezing the meter.
  const VOICE_WORDS = {
    OFFLINE: 'OFF',
    IDLE: 'IDLE',
    LISTEN: 'LISTEN',
    THINK: 'THINK',
    SPEAK: 'SPEAK',
  };

  /** Reactor bloom = CPU load + how loud the room is. */
  function paintReactor() {
    const pulse = $('#reactorPulse');
    if (!pulse) return;
    const cpu = clamp(num(STATE.shown.cpu), 0, 100);
    const voice = VOICE.on ? clamp(VOICE.mic, 0, 1) : 0;
    pulse.style.opacity = clamp(0.18 + (cpu / 100) * 0.3 + voice * 0.42, 0, 0.96).toFixed(3);
  }

  async function fetchVoice() {
    const url = CFG.voiceEndpoints[VOICE.idx % CFG.voiceEndpoints.length];
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), CFG.voice.timeoutMs);
    try {
      const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
      if (!res.ok) throw new Error(String(res.status));
      const s = await res.json();
      if (!s || typeof s !== 'object') throw new Error('no state');
      return s;
    } finally {
      clearTimeout(timer);
    }
  }

  async function pollVoice() {
    try {
      const s = await fetchVoice();
      VOICE.on = true;
      applyVoice(s);
    } catch (e) {
      VOICE.idx += 1;                    // rotate endpoints, same as telemetry
      if (VOICE.on) {
        VOICE.on = false;
        applyVoice({ status: 'OFFLINE', mic: 0, you: '', jarvis: '' });
      }
    }
  }

  function applyVoice(s) {
    const status = String(s.status || 'OFFLINE').toUpperCase();
    VOICE.status = status;

    // The assistant may change protocol too (switch_persona tool). Only react
    // when the published value actually changes, otherwise the next 130 ms poll
    // would undo a click on the brand. The *first* value is just a baseline:
    // /state always starts at "jarvis", so letting it through would stomp a
    // choice restored from localStorage or ?persona=.
    const remote = String(s.persona || '').toLowerCase();
    if (remote && remote !== VOICE.remotePersona) {
      const first = VOICE.remotePersona === '';
      VOICE.remotePersona = remote;
      if (!(first && localOverride)) setPersona(remote);
    }
    // A missing link is not a quiet microphone: show zero, never a guess.
    VOICE.mic = VOICE.on ? clamp(num(s.mic), 0, 1) : 0;
    VOICE.speaking = VOICE.on && s.speaking === true;
    VOICE.thinking = VOICE.on && s.thinking === true;
    VOICE.you = typeof s.you === 'string' ? s.you : '';
    VOICE.jarvis = typeof s.jarvis === 'string' ? s.jarvis : '';
    VOICE.turn = num(s.turn);

    const row = $('.rail__voice');
    if (row) {
      row.classList.toggle('is-speaking', VOICE.speaking);
      row.classList.toggle('is-offline', !VOICE.on);
    }
    setText('#railVoice', VOICE.on ? (VOICE_WORDS[status] || status) : 'OFF');

    const mic = $('#railMic');
    if (mic) mic.style.width = `${(VOICE.mic * 100).toFixed(0)}%`;

    const box = $('#voice');
    if (box) {
      box.classList.toggle('is-speaking', VOICE.speaking);
      box.classList.toggle('is-offline', !VOICE.on);
    }
    setText('#voiceYou', VOICE.on ? (VOICE.you || '\u2014') : '\u2014');
    // A bridge that is up but never published is still not JARVIS talking.
    setText('#voiceJarvis', (!VOICE.on || status === 'OFFLINE')
      ? 'VOICE LINK OFFLINE'
      : (VOICE.jarvis || 'STANDBY'));

    paintReactor();
  }


  /* ==========================================================================
     4. BINDING
     ========================================================================== */

  function setMode(mode) {
    const isLive = mode === 'LIVE';
    const modeText = $('#modeText');
    const railMode = $('#railMode');
    const railFoot = $('#railFoot');
    const ledLink = $('#ledLink');
    if (modeText) modeText.textContent = isLive ? 'TELEMETRY LINK' : 'SIMULATION';
    if (railMode) railMode.textContent = isLive ? 'LIVE' : 'SIM';
    if (railFoot) railFoot.textContent = isLive ? 'SYNCED' : 'NO BRIDGE';
    if (ledLink) ledLink.classList.toggle('led--red', !isLive);
    if (railFoot) railFoot.closest('.rail__foot')?.classList.toggle('is-sim', !isLive);
  }

  function apply(d) {
    if (!d) return;

    const cpu = num(d.cpu?.pct);
    const mem = num(d.mem?.pct);
    const gpuPct = d.gpu?.pct;
    const gpuHas = typeof gpuPct === 'number';
    const gpuShown = gpuHas ? gpuPct : 0;
    const rx = num(d.net?.rx), tx = num(d.net?.tx);
    const netPct = clamp(Math.log10(1 + rx + tx) / Math.log10(1 + 5000) * 100, 0, 100);

    // smooth the numeric display so gauges never snap
    STATE.shown.cpu = lerp(STATE.shown.cpu, cpu, 0.45);
    STATE.shown.mem = lerp(STATE.shown.mem, mem, 0.45);
    STATE.shown.gpu = lerp(STATE.shown.gpu, gpuShown, 0.45);
    STATE.shown.net = lerp(STATE.shown.net, netPct, 0.35);
    STATE.shown.rx = lerp(STATE.shown.rx, rx, 0.5);
    STATE.shown.tx = lerp(STATE.shown.tx, tx, 0.5);

    const v = {
      cpu: STATE.shown.cpu,
      mem: STATE.shown.mem,
      gpu: STATE.shown.gpu,
    };

    logHist('cpu', v.cpu);
    logHist('mem', v.mem);
    logHist('gpu', v.gpu);
    logHist('net', STATE.shown.net);

    // ---- hub -------------------------------------------------------------
    paintCoreArcs(v);
    paintHubBars(STATE.hist[STATE.selected]);
    setText('#valCPU', gpuHas || true ? v.cpu.toFixed(0) + '%' : '--');
    setText('#valMEM', v.mem.toFixed(0) + '%');
    setText('#valGPU', gpuHas ? v.gpu.toFixed(0) + '%' : '--');

    // reactor breathes with CPU load and flares with the microphone
    paintReactor();

    // ---- diagnostics -----------------------------------------------------
    bindTemps(d);
    bindGraphs(d);

    // ---- storage ---------------------------------------------------------
    bindDisks(d);
    bindUsb(d);

    // ---- proximity -------------------------------------------------------
    setText('#auxConns', d.conns == null ? '--' : String(d.conns).padStart(2, '0'));
    setNum('#auxRx', rx.toFixed(1), 'kB/s');
    setNum('#auxTx', tx.toFixed(1), 'kB/s');
    paintRadar(d, rx + tx);

    // ---- rail ------------------------------------------------------------
    const batt = d.battery;
    railRow('#railCpu', '#railCpuV', v.cpu);
    railRow('#railMem', '#railMemV', v.mem);
    railRow('#railGpu', '#railGpuV', gpuHas ? v.gpu : null);
    railRow('#railDisk', '#railDiskV', d.disks?.[0]?.pct);
    railRow('#railNet', '#railNetV', STATE.shown.net, (v) => v.toFixed(0));
    railRow('#railProc', '#railProcV',
      clamp(num(d.procs) / 6, 0, 100), null, num(d.procs).toFixed(0));
    railRow('#railBatt', '#railBattV', batt ? batt.pct : null, null,
      batt ? String(batt.pct) : '--');

    // ---- deck ------------------------------------------------------------
    const ghz = d.cpu?.freq ? (d.cpu.freq / 1000).toFixed(2) : null;
    if (ghz) setNum('#deckClock', ghz, 'GHz');
    else setText('#deckClock', '--');
    if (d.temps?.gpu != null) setNum('#deckTemp', String(Math.round(d.temps.gpu)), '&deg;C');
    else setText('#deckTemp', '--');
    setText('#deckUp', uptime(d.uptime));
    const freeRam = d.mem?.total && d.mem?.used ? (d.mem.total - d.mem.used) : null;
    if (freeRam == null) setText('#deckFree', '--');
    else setNum('#deckFree', freeRam.toFixed(1), 'GB');

    // ---- strip -----------------------------------------------------------
    setText('#stripGpu', shortGpu(d.gpu?.name));
  }

  function setText(sel, text) {
    const el = $(sel);
    if (el && el.textContent !== text) el.textContent = text;
  }

  /**
   * Write a value plus a styled unit. The markup wraps units in <em>/<i> so
   * they render smaller and dimmer than the number; a bare textContent write
   * would throw that away, so the unit is rebuilt as an element each time.
   * `unit` is always a literal from this file - never user data.
   */
  function setNum(sel, value, unit, tag = 'em') {
    const el = $(sel);
    if (!el) return;
    el.innerHTML = unit ? `${value} <${tag}>${unit}</${tag}>` : String(value);
  }

  function shortGpu(name) {
    if (!name) return 'GRAPHICS';
    const s = String(name)
      .replace(/NVIDIA\s+/i, '')
      .replace(/GeForce\s+/i, '')
      .replace(/AMD\s+/i, '')
      .replace(/Radeon\s+/i, '')
      .replace(/Laptop GPU/i, '')
      .replace(/\s*Graphics\s*/i, ' ')
      .trim();
    return s.toUpperCase().slice(0, 22) || 'GRAPHICS';
  }

  function uptime(sec) {
    const s = num(sec, 0);
    if (!s) return '--:--';
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }

  function bindTemps(d) {
    const gpuT = d.temps?.gpu;
    const cpuT = d.temps?.cpu;
    // In simulation nothing is measured, so the provenance tag must not claim
    // a sensor reading even though the numbers look plausible.
    const simulated = d.sim === true;

    // If a sensor is missing, derive a plausible value from load and mark it.
    const cpuPct = num(d.cpu?.pct);
    const cpuEst = cpuT != null ? cpuT : 38 + cpuPct * 0.42;
    const gpuEst = gpuT != null ? gpuT : 40 + num(d.gpu?.pct) * 0.4;

    const gpuArc = $('#gpuArc');
    const coreArc = $('#coreArc');
    if (gpuArc) gpuArc.style.strokeDashoffset = String(clamp(100 - ((gpuEst - 30) / 70) * 100, 0, 100));
    if (coreArc) coreArc.style.strokeDashoffset = String(clamp(100 - ((cpuEst - 30) / 70) * 100, 0, 100));

    setNum('#gpuVal', Math.round(gpuEst), '&deg;C', 'i');
    setNum('#coreVal', Math.round(cpuEst), '&deg;C', 'i');

    // provenance tags: measured, derived, or invented for the demo
    setText('#gpuSrc', simulated ? 'SIM' : gpuT == null ? 'EST' : 'GPU');
    setText('#coreSrc', simulated ? 'SIM' : cpuT == null ? 'EST' : 'PKG');

    const fans = d.fans || {};
    if (fans.aux != null) setNum('#fanAux', Math.round(fans.aux), 'RPM');
    else setText('#fanAux', 'N/A');
    if (fans.cpu != null) setNum('#fanCpu', Math.round(fans.cpu), 'RPM');
    else setText('#fanCpu', 'N/A');
  }

  const gDown = { bars: null }, gUp = { bars: null };

  function bindGraphs(d) {
    const rx = num(d.net?.rx), tx = num(d.net?.tx);
    setText('#downVal', rx >= 1024 ? (rx / 1024).toFixed(2) : rx.toFixed(1));
    setText('#downUnit', rx >= 1024 ? 'MB/s' : 'kB/s');
    setText('#upVal', tx >= 1024 ? (tx / 1024).toFixed(2) : tx.toFixed(1));
    setText('#upUnit', tx >= 1024 ? 'MB/s' : 'kB/s');

    if (gDown.bars) paintGraph(gDown.bars, clamp(Math.log10(1 + rx) / Math.log10(1 + 3000) * 100, 4, 100));
    if (gUp.bars) paintGraph(gUp.bars, clamp(Math.log10(1 + tx) / Math.log10(1 + 3000) * 100, 4, 100));
  }

  function bindDisks(d) {
    const disks = Array.isArray(d.disks) ? d.disks : [];
    const rows = [1, 2];

    // Row 1 is the system volume, row 2 the next volume, or the aggregate
    // when the machine only has one - better than an empty slot.
    let second = disks[1];
    if (!second && disks.length === 1) {
      const tot = disks.reduce((a, v) => a + num(v.total), 0);
      const used = disks.reduce((a, v) => a + num(v.used), 0);
      second = { letter: 'ALL', pct: tot ? (used / tot) * 100 : 0 };
    }

    const pick = [disks[0], second];
    rows.forEach((n, i) => {
      const vol = pick[i];
      const name = `#volName${n}`, pctEl = `#volPct${n}`, bar = `#volBar${n}`;
      const label = !vol ? 'VOLUME --'
        : vol.letter === 'ALL' ? 'ALL VOLUMES'
        : `VOLUME ${vol.letter}`;
      setText(name, label);
      setText(pctEl, vol ? `${Math.round(num(vol.pct))}%` : '--%');
      setSegbar($(bar), vol ? num(vol.pct) : 0);
    });

    const busiest = disks[0];
    const dial = $('#dialSpin');
    if (dial) dial.style.transform = `rotate(${clamp(num(busiest?.pct) * 3.6, 0, 360)}deg)`;
    setText('#dialVal', busiest ? `${Math.round(num(busiest.pct))}%` : '--');

    const free = disks.reduce((a, v) => a + num(v.free), 0);
    setText('#tagFree', free ? `${free.toFixed(0)}G` : 'FREE');
    setText('#tagCount', `${String(disks.length).padStart(2, '0')}x`);
  }

  function bindUsb(d) {
    const usb = Array.isArray(d.usb) ? d.usb : [];
    const rows = $$('#usbList .usb__drive');

    rows.forEach((row, i) => {
      const drive = usb[i];
      const tag = row.querySelector('.usb__tag');
      const bar = row.querySelector('.segbar');
      const pct = row.querySelector('.usb__pct');
      row.classList.toggle('is-absent', !drive);

      if (drive) {
        if (tag) tag.textContent = String(drive.letter).replace(/^([A-Za-z])$/, '$1:');
        setSegbar(bar, num(drive.pct));
        if (pct) pct.textContent = `${Math.round(num(drive.pct))}%`;
        if (bar) bar.dataset.pulse = '1';
      } else {
        if (tag) tag.textContent = '--';
        setSegbar(bar, 0);
        if (pct) pct.textContent = '--';
      }
    });

    setText('#usbCount', `${usb.length} ${usb.length === 1 ? 'DEVICE' : 'DEVICES'}`);
    setText('#usbState', usb.length ? 'MOUNTED' : 'NO MEDIA');
    const led = $('#usbLed');
    if (led) led.classList.toggle('led--off', !usb.length);
  }

  const radarBlips = [];
  function buildRadar() {
    const host = $('#radarBlips');
    if (!host) return;
    // 5 fixed bearings; which of them are "hot" follows the traffic volume.
    const spots = [
      [65, 35], [36, 61], [59, 69], [28, 38], [70, 58],
    ];
    spots.forEach(([x, y]) => {
      const c = mk('circle', { cx: x, cy: y, r: 2.4, class: 'mr__blip' });
      host.appendChild(c);
      radarBlips.push(c);
    });
  }

  function paintRadar(d, traffic) {
    const n = clamp(Math.round(Math.log10(1 + traffic) * 1.4), 1, radarBlips.length);
    radarBlips.forEach((b, i) => b.classList.toggle('mr__blip--hot', i < n));
    const sweep = $('#mrSweep');
    if (sweep) {
      const secs = clamp(9 - Math.log10(1 + traffic), 2.2, 9);
      sweep.style.animationDuration = `${secs.toFixed(2)}s`;
    }
  }

  function railRow(barSel, valSel, pct, fmt, rawText) {
    const bar = $(barSel);
    const val = $(valSel);
    if (pct == null) {
      if (bar) bar.style.width = '0%';
      if (val) val.textContent = '--';
      return;
    }
    const p = clamp(num(pct), 0, 100);
    if (bar) bar.style.width = `${p.toFixed(1)}%`;
    if (val) val.textContent = rawText != null ? rawText : (fmt ? fmt(p) : p.toFixed(0));
  }

  /* ==========================================================================
     5. EFFECTS
     ========================================================================== */

  function initClock() {
    const el = $('#clock');
    const ghost = $('.hub__clockv--ghost');
    if (!el) return;

    const paint = () => {
      const d = new Date();
      const text = String(d.getHours()).padStart(2, '0') + ':' +
                   String(d.getMinutes()).padStart(2, '0');
      el.textContent = text;
      if (ghost) ghost.textContent = text;
    };

    paint();
    const now = new Date();
    const msToNextMinute = (60 - now.getSeconds()) * 1000 - now.getMilliseconds();
    setTimeout(() => {
      paint();
      setInterval(paint, CFG.clock.updateMs);
    }, Math.max(250, msToNextMinute));
  }

  /** Decode/typing effect used by the boot sequence and the brand. */
  function decode(el, finalText, ms = 900) {
    if (!el || VERIFY) {
      if (el) el.textContent = finalText;
      return;
    }
    const glyphs = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#/\\<>*=+-';
    const start = performance.now();
    const tick = (t) => {
      const k = clamp((t - start) / ms, 0, 1);
      const keep = Math.floor(finalText.length * k);
      let out = finalText.slice(0, keep);
      for (let i = keep; i < finalText.length; i++) {
        out += finalText[i] === ' ' ? ' ' : glyphs[(Math.random() * glyphs.length) | 0];
      }
      el.textContent = out;
      if (k < 1) requestAnimationFrame(tick);
      else el.textContent = finalText;
    };
    requestAnimationFrame(tick);
  }

  function initBoot() {
    const boot = $('#boot');
    if (!boot) return;
    if (VERIFY) {
      boot.remove();
      return;
    }
    const bar = $('#bootBar');
    const pct = $('#bootPct');
    const line = $('#bootLine');
    const lines = [
      'ARC REACTOR ONLINE',
      'SUIT TELEMETRY LINK',
      'CALIBRATING OPTICS',
      'MK-LXXXV READY',
    ];
    let p = 0;
    const step = () => {
      p = Math.min(100, p + 7 + Math.random() * 13);
      if (bar) bar.style.width = p + '%';
      if (pct) pct.textContent = Math.round(p) + '%';
      if (line) line.textContent = lines[Math.min(lines.length - 1, Math.floor(p / 26))];
      if (p < 100) {
        setTimeout(step, 60 + Math.random() * 90);
      } else {
        setTimeout(() => {
          boot.classList.add('is-done');
          setTimeout(() => boot.remove(), 900);
        }, 260);
      }
    };
    setTimeout(step, 120);
  }

  /* -- leader-line callouts -------------------------------------------------- */
  const CALLOUTS = [
    { panel: '.panel--diag', label: '01' },
    { panel: '.panel--disk', label: '02' },
    { panel: '.panel--usb',  label: '03' },
    { panel: '.panel--aux',  label: '04' },
  ];

  function drawCallouts() {
    const svg = $('#callouts');
    const hub = $('#hub');
    if (!svg || !hub) return;

    const stage = $('#stage');
    const W = stage.clientWidth, H = stage.clientHeight;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('width', W);
    svg.setAttribute('height', H);
    svg.innerHTML = '';

    const hb = hub.getBoundingClientRect();
    const hx = hb.left + hb.width / 2;
    const hy = hb.top + hb.height / 2;
    const r = hb.width * 0.47;

    CALLOUTS.forEach(({ panel, label }) => {
      const el = document.querySelector(panel);
      if (!el) return;
      const head = el.querySelector('.panel__head') || el;
      const pb = head.getBoundingClientRect();
      const px = pb.left + pb.width / 2;
      const py = pb.top + pb.height / 2;

      let dx = px - hx, dy = py - hy;
      const len = Math.hypot(dx, dy) || 1;
      dx /= len; dy /= len;

      const sx = hx + dx * r, sy = hy + dy * r;
      // elbow: leave the hub perpendicular to the run, then angle to the panel
      const ex = sx + (px - sx) * 0.45;
      const ey = sy;
      const ex2 = px - dx * Math.min(60, len * 0.18);

      const g = mk('g', { class: 'callout' });
      g.appendChild(mk('polyline', {
        points: `${sx.toFixed(1)},${sy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)} ${ex2.toFixed(1)},${py.toFixed(1)} ${px.toFixed(1)},${py.toFixed(1)}`,
        class: 'callout__line',
      }));
      g.appendChild(mk('circle', { cx: sx.toFixed(1), cy: sy.toFixed(1), r: 2.4, class: 'callout__dot' }));
      g.appendChild(mk('circle', { cx: px.toFixed(1), cy: py.toFixed(1), r: 1.8, class: 'callout__dot callout__dot--end' }));
      const t = mk('text', {
        x: (ex + 6).toFixed(1), y: (ey - 5).toFixed(1), class: 'callout__tag',
      });
      t.textContent = label;
      g.appendChild(t);
      svg.appendChild(g);
    });
  }

  /* ==========================================================================
     5b. PERSONAS  (J.A.R.V.I.S / F.R.I.D.A.Y / U.L.T.R.O.N)
     --------------------------------------------------------------------------
     The palette itself lives in CSS (registered custom properties, so it
     interpolates). This only picks the persona, plays the shift and keeps the
     labels in sync. A persona may also arrive from the bridge as
     `state.persona`, which is how the assistant can change it by voice.
     ========================================================================== */

  const PERSONAS = {
    jarvis: { label: 'J.A.R.V.I.S', title: 'MK-LXXXV // FLIGHT HUD',   step: 0 },
    friday: { label: 'F.R.I.D.A.Y', title: 'MK-LXXXV // FRIDAY LINK',   step: 1 },
    ultron: { label: 'U.L.T.R.O.N', title: 'MK-LXXXV // HOSTILE LINK',  step: 2 },
  };
  const PERSONA_ORDER = ['jarvis', 'friday', 'ultron'];
  const PERSONA_KEY = 'mk85.persona';
  const MORPH_MS = 1450;                    // keep in step with --morph-dur
  const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let persona = 'jarvis';
  let morphTimer = 0;
  // True when the persona came from the URL or localStorage. The first value the
  // bridge reports then only sets the baseline: it must not overwrite a choice
  // the user already made, because /state always starts at "jarvis".
  let localOverride = false;

  function setPersona(name, opts = {}) {
    const key = String(name || '').toLowerCase();
    if (!PERSONAS[key] || key === persona) return false;
    persona = key;
    const p = PERSONAS[key];

    document.documentElement.dataset.persona = key;
    document.title = p.title;

    const brand = $('#brand');
    if (brand) brand.textContent = p.label;          // no decode: it must be readable at once
    const mn = $('#morphName');
    if (mn) {
      mn.textContent = p.label;
      mn.dataset.text = p.label;                     // chromatic pseudo-copies
    }

    // restart the overlay animation even if one is still running
    const morph = $('#morph');
    if (morph && !VERIFY) {
      morph.classList.remove('is-on');
      document.documentElement.classList.remove('is-morphing');
      clearTimeout(morphTimer);
      if (!REDUCED_MOTION) {
        void morph.offsetWidth;                      // force reflow
        morph.classList.add('is-on');
        document.documentElement.classList.add('is-morphing');
        // Chrome can leave re-added CSS animations pending forever when a
        // shift interrupts another. Force them onto the timeline.
        if (morph.getAnimations) {
          for (const anim of morph.getAnimations({ subtree: true })) {
            anim.cancel();
            anim.play();
            if (document.timeline.currentTime != null) {
              anim.startTime = document.timeline.currentTime;
            }
          }
        }
        morphTimer = setTimeout(() => {
          morph.classList.remove('is-on');
          document.documentElement.classList.remove('is-morphing');
        }, MORPH_MS);
      }
    }

    if (opts.persist !== false) {
      try { localStorage.setItem(PERSONA_KEY, key); } catch (e) { /* private mode */ }
    }
    return true;
  }

  function cyclePersona() {
    const i = PERSONA_ORDER.indexOf(persona);
    setPersona(PERSONA_ORDER[(i + 1) % PERSONA_ORDER.length]);
  }

  function initPersonas() {
    // A remembered choice beats the default; an explicit ?persona= beats both,
    // because the screenshot harness needs to render a named one.
    let start = 'jarvis';
    const asked = (params.get('persona') || '').toLowerCase();
    if (PERSONAS[asked]) {
      start = asked;
      localOverride = true;
    } else {
      try {
        const saved = (localStorage.getItem(PERSONA_KEY) || '').toLowerCase();
        if (PERSONAS[saved]) {
          start = saved;
          localOverride = true;
        }
      } catch (e) { /* private mode */ }
    }
    // Apply without the overlay: this is the board settling, not a shift.
    persona = start;
    document.documentElement.dataset.persona = start;
    document.title = PERSONAS[start].title;
    const brand = $('#brand');
    if (brand) brand.textContent = PERSONAS[start].label;
    const mn = $('#morphName');
    if (mn) {
      mn.textContent = PERSONAS[start].label;
      mn.dataset.text = PERSONAS[start].label;
    }

    const brand2 = $('#brand');
    if (brand2) {
      brand2.setAttribute('role', 'button');
      brand2.setAttribute('tabindex', '0');
      brand2.setAttribute('title', 'Switch protocol: JARVIS -> FRIDAY -> ULTRON');
      brand2.addEventListener('click', () => cyclePersona());
      brand2.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); cyclePersona(); }
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === '1') setPersona('jarvis');
      else if (e.key === '2') setPersona('friday');
      else if (e.key === '3') setPersona('ultron');
    });

    // no point animating a shift that only exists to be photographed
    window.MK85 = window.MK85 || {};
    window.MK85.setPersona = (n) => setPersona(n);
    window.MK85.persona = () => persona;
  }

  /* -- parallax -------------------------------------------------------------- */

  function initParallax() {
    if (VERIFY) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (window.matchMedia('(hover: none)').matches) return;

    const stage = $('#stage');
    const hubSvg = $('.hub__svg');
    let tx = 0, ty = 0, cx = 0, cy = 0, raf = 0;

    const onMove = (e) => {
      tx = (e.clientX / window.innerWidth - .5) * 2;
      ty = (e.clientY / window.innerHeight - .5) * 2;
      if (!raf) raf = requestAnimationFrame(loop);
    };

    const loop = () => {
      cx = lerp(cx, tx, .07);
      cy = lerp(cy, ty, .07);
      // .hub itself is positioned with translate(-50%,-50%) and owns the boot
      // animation, so the parallax rides on the inner <svg> instead.
      if (hubSvg) hubSvg.style.transform = `translate(${(-cx * 5).toFixed(2)}px, ${(-cy * 5).toFixed(2)}px)`;
      if (stage) stage.style.setProperty('--mx', cx.toFixed(3));
      raf = Math.abs(cx - tx) > .001 || Math.abs(cy - ty) > .001
        ? requestAnimationFrame(loop) : 0;
    };

    window.addEventListener('pointermove', onMove, { passive: true });
  }

  /* -- selection ------------------------------------------------------------- */
  function initSelection() {
    const wedges = $$('#hub .core__wedge');
    const apply = () => {
      wedges.forEach((w) => w.classList.toggle('is-sel', w.dataset.metric === STATE.selected));
      $$('#hub .segarc__fill').forEach((a) => {
        a.classList.toggle('is-sel', a.dataset.metric === STATE.selected);
      });
      $$('#hub .core__labels text').forEach((t) => t.classList.remove('is-sel'));
      paintHubBars(STATE.hist[STATE.selected]);
    };

    wedges.forEach((w) => {
      w.addEventListener('click', () => {
        STATE.selected = w.dataset.metric;
        apply();
      });
    });
    apply();
  }

  /* ==========================================================================
     BOOTSTRAP
     ========================================================================== */
  function init() {
    buildTicks();
    buildHubBars();
    buildCoreArcs();
    buildReactor();
    buildMicroLabels();
    buildRadar();

    gDown.bars = buildGraph($('#gDown'));
    gUp.bars = buildGraph($('#gUp'));
    $$('.segbar').forEach(buildSegbar);

    initClock();
    initSelection();
    initPersonas();
    initBoot();
    initParallax();

    decode($('#brand'), PERSONAS[persona].label, 1100);

    drawCallouts();
    setTimeout(drawCallouts, 120);
    window.addEventListener('resize', () => {
      clearTimeout(init._t);
      init._t = setTimeout(drawCallouts, 120);
    });

    setMode('SIM');
    poll();
    setInterval(poll, CFG.poll.everyMs);

    applyVoice({ status: 'OFFLINE' });
    pollVoice();
    setInterval(pollVoice, CFG.voice.everyMs);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
