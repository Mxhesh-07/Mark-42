// J.A.R.V.I.S. HUD client.
//
// The Python process is the brain: it owns the microphone, the Gemini Live
// session and the tools. This page only watches. It polls /api/state twenty
// times a second, paints what changed, and sends back the three things a HUD
// is allowed to send: typed text, stop, mute.
//
// The globe is the ULTRON orb (orb.js) driven by the same kind of data app.js
// feeds it. Browser audio is not in the loop, so the waveform is synthesised
// from the microphone level Python reports — enough for the ring to move with
// a real voice without opening a second input device.

import { Orb } from './orb.js';
import { sfx, unlock } from './sfx.js';

const $ = (sel) => document.querySelector(sel);
const body = document.body;
const POLL_MS = 50;
const POLL_HIDDEN_MS = 600;

const state = {
  board: null,
  connected: false,
  fails: 0,
  mic: 0,
  micTarget: 0,
  speaking: false,
  listening: false,
  thinking: false,
  muted: false,
  turns: 0,
  logStamp: '',
  echo: null,             // optimistic copy of the line just typed
  booted: false,
  toastUntil: 0,
  cpuHist: [],
  confirmId: null,         // id of the panel currently painted
  confirmAnswered: null,   // id answered, waiting for Python to clear it
  confirmLeft: 0,          // seconds, recomputed from the panel's deadline
  confirmPaintedAt: 0,
};

// --------------------------------------------------------------------------
// boot
// --------------------------------------------------------------------------
const BOOT_LINES = [
  ['ARC REACTOR', 'ONLINE'],
  ['AUDIO ENGINE', 'READY'],
  ['MEMORY CORE', 'SYNC'],
  ['GEMINI UPLINK', 'NEGOTIATING'],
  ['TOOL BUS', 'ARMED'],
];

function boot() {
  const log = $('#boot-log');
  let i = 0;
  const tick = () => {
    if (i >= BOOT_LINES.length) {
      setTimeout(finishBoot, 320);
      return;
    }
    const [name, status] = BOOT_LINES[i++];
    log.insertAdjacentHTML('beforeend', `<div>${name} <b>&middot; ${status}</b></div>`);
    setTimeout(tick, 180 + Math.random() * 90);
  };
  setTimeout(tick, 160);

  const skip = () => finishBoot();
  window.addEventListener('keydown', skip, { once: true });
  $('#boot').addEventListener('click', skip, { once: true });
  // Never let a failure in this sequence hide the HUD behind an overlay.
  setTimeout(finishBoot, 4200);
}

function finishBoot() {
  if (state.booted) return;
  state.booted = true;
  body.classList.add('powering');
  body.classList.add('powered');
  const node = $('#boot');
  node.classList.add('gone');
  setTimeout(() => node.remove(), 700);
  setTimeout(() => body.classList.remove('powering'), 1400);
}

// --------------------------------------------------------------------------
// globe
// --------------------------------------------------------------------------
let orb = null;
let orbFailed = false;
try {
  orb = new Orb($('#orb'));
  orb.setColors('#0a4f73', '#38d6ff', '#e6fbff', '#040608');
} catch (err) {
  orbFailed = true;
  body.classList.add('no-webgl');
  console.warn('[hud] globe unavailable:', err);
}

const wave = new Uint8Array(256).fill(128);
const freq = new Uint8Array(128);
let t = 0;
let prevFrame = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - prevFrame) / 1000);
  prevFrame = now;
  t += dt;

  // Ease the level so a chunked RMS reading does not make the globe twitch.
  state.mic += (state.micTarget - state.mic) * (1 - Math.exp(-dt * 14));

  const live = state.speaking ? 0.55 + state.mic * 0.45 : state.listening ? state.mic : 0;
  for (let i = 0; i < 256; i++) {
    const p = i / 256;
    let v = 128;
    if (live > 0.01) {
      const carrier = Math.sin(p * Math.PI * 2 * 7 + t * 5.5);
      const detail = Math.sin(p * Math.PI * 2 * 19 - t * 3.1) * 0.45;
      const envelope = Math.sin(p * Math.PI);           // fade the ends
      v = 128 + Math.round((carrier + detail) * envelope * live * 112);
    } else {
      v = 128 + Math.round(Math.sin(p * Math.PI * 2 + t * 0.8) * 1.5);
    }
    wave[i] = Math.max(0, Math.min(255, v));
  }
  for (let i = 0; i < 128; i++) {
    const decay = Math.exp(-i / (state.speaking ? 26 : 15));
    freq[i] = Math.max(0, Math.min(255,
      Math.round((live * 240 + (state.thinking ? 26 : 0)) * decay * (0.7 + 0.3 * Math.sin(t * 2 + i * 0.4)))));
  }

  if (orb) {
    orb.update(dt, {
      wave, freq,
      level: Math.min(1, state.mic + (state.speaking ? 0.22 : 0)),
      speaking: state.speaking,
      listening: state.listening,
      thinking: state.thinking,
    });
    if (orb.moved) placeHud(orb);
  }

  // Meter + value text, cheap enough per frame.
  const pct = Math.round(state.mic * 100);
  const bar = $('#mic-bar');
  if (bar) bar.style.width = pct + '%';
  const val = $('#mic-val');
  if (val) val.textContent = pct + '%';

  if (state.confirmId) paintConfirmTimer();

  requestAnimationFrame(frame);
}

function placeHud(o) {
  const { x, y, r } = o.screen;
  const status = $('#status');
  if (!status) return;
  Object.assign(status.style, { top: `${y + r + 10}px`, left: `${x}px` });
  document.documentElement.style.setProperty('--globe-bottom', `${Math.round(y + r + 44)}px`);
}

requestAnimationFrame(frame);

// --------------------------------------------------------------------------
// polling
// --------------------------------------------------------------------------
async function poll() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const board = await res.json();
    state.fails = 0;
    if (!state.connected) {
      state.connected = true;
      toast('Uplink established', 1600);
    }
    render(board);
  } catch (err) {
    state.fails += 1;
    if (state.fails === 4) {
      state.connected = false;
      paintStatus();
      toast('HUD link lost — is J.A.R.V.I.S. running?', 4000);
    }
  } finally {
    setTimeout(poll, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
  }
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) poll();
});

// --------------------------------------------------------------------------
// render
// --------------------------------------------------------------------------
function render(board) {
  const prev = state.board;
  state.board = board;
  state.micTarget = Math.max(0, Math.min(1, Number(board.mic) || 0));
  state.speaking = !!board.speaking;
  state.thinking = !!board.thinking;
  state.listening = board.status === 'LISTEN';
  state.muted = !!board.muted;
  state.turns = Number(board.turn) || 0;

  if (!prev || prev.turn !== board.turn || prev.you !== board.you) {
    if (board.you) state.echo = null;
  }

  body.classList.toggle('speaking', state.speaking);
  body.classList.toggle('thinking', state.thinking);
  body.classList.toggle('listening', state.listening);
  body.classList.toggle('muted', state.muted);
  body.classList.toggle('awaiting', !!board.confirm);
  paintStatus();

  paintPills(board);
  paintTranscript(board);
  paintPanels(board);
  paintConfirm(board);
  paintTelemetry(board.telemetry || {});
  paintClock();
}

function paintStatus() {
  let text = 'STANDING BY';
  if (!state.connected) text = 'NO UPLINK';
  else if (state.board && state.board.confirm) text = 'APPROVAL REQUIRED';
  else if (state.muted) text = 'MICROPHONE MUTED';
  else if (state.speaking) text = 'SPEAKING';
  else if (state.thinking) text = 'PROCESSING';
  else if (state.listening) text = 'LISTENING';

  const node = $('#status-text');
  if (node && node.textContent !== text) {
    node.textContent = text;
    const box = $('#status');
    box.classList.remove('changed');
    void box.offsetWidth;
    box.classList.add('changed');
  }
}

function paintPills(board) {
  const set = (name, on) => {
    const el = $('#pill-' + name);
    if (el) el.classList.toggle('on', !!on);
  };
  set('core', true);
  set('audio', !state.muted && (board.status !== 'STANDBY' || state.connected));
  set('link', state.connected);
  const session = $('#session-state');
  if (session) {
    session.textContent = state.connected ? (board.connected ? 'LIVE' : 'IDLE') : 'OFFLINE';
    session.className = state.connected ? '' : 'error';
  }
}

function paintTranscript(board) {
  const log = $('#log');
  if (!log) return;

  const entries = Array.isArray(board.log) ? board.log : [];
  const stamp = entries.length + ':' + (entries.length ? entries[entries.length - 1].ts : 0) +
    ':' + (entries.length ? entries[entries.length - 1].text.length : 0) + ':' + (state.echo ? 'e' : '');

  if (stamp !== state.logStamp) {
    state.logStamp = stamp;
    const pin = nearBottom(log);
    const frag = document.createDocumentFragment();

    for (const e of entries.slice(-80)) {
      frag.appendChild(lineNode(e.role, e.text, false));
    }
    // The optimistic line for text just sent, until Python logs the real turn.
    if (state.echo) frag.appendChild(lineNode('user', state.echo, true));
    // Live reply preview from the streaming transcription.
    if (board.jarvis && !state.echo) {
      const live = lineNode('jarvis', board.jarvis, true);
      live.classList.add('interim');
      frag.appendChild(live);
    }

    log.replaceChildren(frag);
    if (pin) log.scrollTop = log.scrollHeight;
  }
}

function lineNode(role, text, pending) {
  const names = { you: 'YOU', user: 'YOU', jarvis: 'J.A.R.V.I.S', ai: 'J.A.R.V.I.S', sys: 'SYS' };
  const cls = role === 'jarvis' || role === 'ai' ? 'jarvis'
    : role === 'you' || role === 'user' ? 'user'
      : role === 'err' ? 'error' : 'sys';
  const node = document.createElement('div');
  node.className = 'line ' + cls + (pending ? ' interim' : '');
  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = names[role] || 'SYS';
  const p = document.createElement('p');
  p.textContent = text;
  node.append(who, p);
  return node;
}

function nearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
}

function paintPanels(board) {
  const mem = $('#memory');
  if (mem) mem.textContent = board.memory || '—';

  const tasks = $('#tasks');
  if (tasks) {
    const list = Array.isArray(board.tasks) ? board.tasks : [];
    tasks.replaceChildren(...list.map((item) => {
      const li = document.createElement('li');
      const raw = String(item);
      li.textContent = raw;
      if (raw.includes('✓') || /done|complete/i.test(raw)) li.className = 'done';
      else if (raw.includes('⟳') || /running|thinking|working/i.test(raw)) li.className = 'active';
      return li;
    }));
  }

  const agent = board.agent || {};
  setText('#agent-name', agent.name || 'Planner');
  const agentState = $('#agent-state');
  if (agentState) {
    const value = String(agent.state || 'IDLE');
    agentState.textContent = value;
    agentState.className = value.toLowerCase();
  }
  setText('#turns', String(state.turns));

  const actions = $('#actions');
  if (actions) {
    const list = Array.isArray(board.actions) ? board.actions.slice(-12).reverse() : [];
    actions.replaceChildren(...list.map((a) => {
      const li = document.createElement('li');
      const status = String(a.status || '').toLowerCase();
      li.className = /run|work|exec/.test(status) ? 'running' : /fail|error/.test(status) ? 'failed' : 'done';
      const t = document.createElement('div');
      t.className = 't';
      const name = document.createElement('span');
      name.textContent = a.name || 'action';
      const st = document.createElement('span');
      st.textContent = a.status || '';
      t.append(name, st);
      li.appendChild(t);
      if (a.detail) {
        const d = document.createElement('div');
        d.className = 'd';
        d.textContent = a.detail;
        li.appendChild(d);
      }
      return li;
    }));
  }
}

// --------------------------------------------------------------------------
// approval modal
// --------------------------------------------------------------------------
// Python publishes the same panel the Tk dialog would show; the page answers
// with a button id ('deny' | 'approve' | 'always'). Deny holds focus, the
// countdown is advisory, and the decision is always validated in Python: a
// button that was not offered, an expired panel or an unknown id all deny.
function paintConfirm(board) {
  const box = $('#confirm');
  if (!box) return;
  const panel = board.confirm;

  if (!panel || !panel.id) {
    if (state.confirmId) closeConfirm();
    return;
  }
  if (panel.id === state.confirmId) return;        // already on screen
  if (panel.id === state.confirmAnswered) return;  // answered, awaiting clear
  if (!state.connected) return;

  const serverNow = Number(board.ts) || Date.now() / 1000;
  const expires = Number(panel.expires);
  const left = Number.isFinite(expires)
    ? Math.max(1, expires - serverNow)
    : (Number(panel.timeout_s) || 30);

  state.confirmId = panel.id;
  state.confirmLeft = left;
  state.confirmPaintedAt = performance.now();

  setText('#cx-summary', panel.summary || 'Approve this action?');

  const detail = $('#cx-detail');
  detail.replaceChildren();
  const add = (label, value, cls) => {
    if (value === undefined || value === null || value === '') return;
    const row = document.createElement('div');
    if (cls) row.className = cls;
    row.textContent = `${label}: ${value}`;
    detail.appendChild(row);
  };
  add('target', panel.target);
  if (panel.risk !== null && panel.risk !== undefined) {
    add('risk', `${Number(panel.risk).toFixed(2)} (${panel.reversibility || '?'}, ${panel.blast_radius || '?'})`, 'risk');
  }
  add('assessment', panel.opinion);

  const row = $('#cx-buttons');
  row.replaceChildren(...(panel.buttons || []).map((spec) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.decision = spec.id;
    btn.textContent = spec.label || spec.id;
    if (spec.default) btn.dataset.default = '1';
    btn.addEventListener('click', () => answerConfirm(spec.id));
    return btn;
  }));

  box.classList.remove('sending');
  box.classList.add('on');
  box.setAttribute('aria-hidden', 'false');
  paintConfirmTimer();
  sfx('action');
  requestAnimationFrame(() => {
    const focus = row.querySelector('[data-default]') || row.firstElementChild;
    if (focus) focus.focus();
  });
}

function answerConfirm(decision) {
  const id = state.confirmId;
  if (!id || state.confirmAnswered === id) return;
  state.confirmAnswered = id;
  const box = $('#confirm');
  if (box) box.classList.add('sending');
  sfx(decision === 'deny' ? 'off' : 'on');
  command({ kind: 'confirm', id, decision });
}

function closeConfirm() {
  const box = $('#confirm');
  if (box) {
    box.classList.remove('on', 'sending');
    box.setAttribute('aria-hidden', 'true');
  }
  state.confirmId = null;
  state.confirmAnswered = null;
}

function paintConfirmTimer() {
  if (!state.confirmId) return;
  const elapsed = (performance.now() - state.confirmPaintedAt) / 1000;
  const left = Math.max(0, state.confirmLeft - elapsed);
  setText('#cx-timer', String(Math.ceil(left)));
}

function paintTelemetry(tm) {  const cpu = Number(tm.cpu);
  if (Number.isFinite(cpu)) {
    setText('#cpu-val', cpu.toFixed(0) + '%');
    const bar = $('#cpu-bar');
    if (bar) bar.style.width = cpu + '%';
    state.cpuHist.push(cpu);
    if (state.cpuHist.length > 48) state.cpuHist.shift();
    drawSpark();
  }
  const mem = Number(tm.mem);
  if (Number.isFinite(mem)) {
    setText('#mem-val', mem.toFixed(0) + '%');
    const bar = $('#mem-bar');
    if (bar) bar.style.width = mem + '%';
  }
  if (tm.load !== undefined) setText('#load-val', String(tm.load));
  if (tm.procs !== undefined) setText('#procs-val', String(tm.procs));
  if (tm.uptime !== undefined) setText('#uptime', duration(tm.uptime));
  const gpu = tm.gpu;
  setText('#gpu-val', gpu ? `${Math.round(gpu.util)}% · ${Math.round(gpu.temp)}°C` : '—');
  setText('#batt-val', tm.battery !== undefined ? `${tm.battery}%${tm.plugged ? ' ⚡' : ''}` : '—');
  if (tm.ts) setText('#host', location.hostname);
}

function drawSpark() {
  const c = $('#cpu-spark');
  if (!c) return;
  const ctx = c.getContext('2d');
  if (!ctx) return;
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  const data = state.cpuHist;
  if (data.length < 2) return;
  const x = (i) => (i / (data.length - 1)) * w;
  const y = (v) => h - (v / 100) * (h - 8) - 4;

  ctx.beginPath();
  data.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(56, 214, 255, 0.5)');
  grad.addColorStop(1, 'rgba(56, 214, 255, 0)');
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  ctx.beginPath();
  data.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.strokeStyle = '#38d6ff';
  ctx.lineWidth = 2;
  ctx.stroke();
}

function setText(sel, text) {
  const el = $(sel);
  if (el && el.textContent !== text) el.textContent = text;
}

function duration(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

function paintClock() {
  const now = new Date();
  setText('#time', now.toLocaleTimeString([], { hour12: false }));
  setText('#date', now.toLocaleDateString([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase());
}

// --------------------------------------------------------------------------
// commands
// --------------------------------------------------------------------------
async function command(payload) {
  try {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(data.error || 'rejected');
    return true;
  } catch (err) {
    toast('Command failed: ' + err.message, 2600);
    return false;
  }
}

function sendText(text) {
  const clean = String(text || '').trim();
  if (!clean) return;
  state.echo = clean;
  state.logStamp = '';          // force a repaint with the echo line
  paintTranscript(state.board || {});
  sfx('send');
  command({ kind: 'text', text: clean });
}

$('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  unlock();
  const input = $('#input');
  sendText(input.value);
  input.value = '';
});

$('#stop').addEventListener('click', () => {
  unlock();
  sfx('off');
  command({ kind: 'stop' });
});

$('#mic').addEventListener('click', () => {
  unlock();
  state.muted = !state.muted;
  sfx(state.muted ? 'off' : 'on');
  command({ kind: 'mute', on: state.muted });
  body.classList.toggle('muted', state.muted);
  paintStatus();
});

for (const chip of document.querySelectorAll('.chip[data-cmd]')) {
  chip.addEventListener('click', () => {
    unlock();
    sendText(chip.dataset.cmd);
  });
}

window.addEventListener('keydown', (e) => {
  if (state.confirmId) {
    // The modal owns the keyboard: Escape denies, Enter activates the focused
    // button (Deny by default). Nothing else is allowed to reach the HUD.
    if (e.key === 'Escape') {
      e.preventDefault();
      answerConfirm('deny');
    }
    return;
  }
  const typing = document.activeElement && ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === 'Escape') {
    command({ kind: 'stop' });
    if (typing) document.activeElement.blur();
  } else if ((e.key === 'm' || e.key === 'M') && !typing) {
    $('#mic').click();
  } else if (e.key === '/' && !typing) {
    e.preventDefault();
    $('#input').focus();
  }
});

// Any first gesture unlocks the interface sounds.
for (const ev of ['pointerdown', 'keydown']) {
  window.addEventListener(ev, () => unlock(), { once: true });
}

// First paint: clocks and a placeholder frame so the HUD is alive before the
// first poll returns.
paintClock();
setInterval(paintClock, 1000);
boot();
poll();
