// Interface sounds, synthesized with Web Audio (no audio files): low, restrained and cinematic.
// Mostly sub-bass weight, filtered noise and soft resonant tones through a dark reverb; no beeps.
// Silent until unlock() is called from a user gesture, inside the iPhone app (which owns the
// audio session natively), and whenever the "Interface sounds" switch is off.

const inApp = /UltronApp/.test(navigator.userAgent);
let ctx = null, master = null, verb = null, noiseBuf = null;
let enabled = true;
try { enabled = localStorage.getItem('fri.sfx') !== 'false'; } catch {}

export function unlock() {
  if (inApp || ctx) return;
  try {
    ctx = new AudioContext();
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.ratio.value = 4;
    master = ctx.createGain();
    master.gain.value = 0.7;
    master.connect(comp).connect(ctx.destination);
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    // A dark hall: decaying noise, low-passed so the tail is warm rather than hissy.
    const len = ctx.sampleRate * 3.2, ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const o = ir.getChannelData(ch);
      let lp = 0;
      for (let i = 0; i < len; i++) { lp += ((Math.random() * 2 - 1) - lp) * 0.18; o[i] = lp * Math.pow(1 - i / len, 3.2); }
    }
    const conv = ctx.createConvolver();
    conv.buffer = ir;
    verb = ctx.createGain();
    verb.gain.value = 0.9;
    verb.connect(conv).connect(master);
  } catch { ctx = null; }
}
export const isEnabled = () => enabled;
export function setEnabled(on) {
  enabled = !!on;
  try { localStorage.setItem('fri.sfx', String(enabled)); } catch {}
}
const ready = () => ctx && (ctx.state === 'running' || (ctx.resume(), true));

// Route a voice to the dry bus and, optionally, the reverb.
function out(node, wet = 0) {
  node.connect(master);
  if (wet > 0) { const s = ctx.createGain(); s.gain.value = wet; node.connect(s).connect(verb); }
}
function env(g, t, peak, attack, dur) {
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(peak, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
}
// A tone: frequency glide f0 -> f1, optional low-pass sweep lp0 -> lp1.
function tone({ type = 'sine', f0, f1 = f0, dur = 0.2, gain = 0.2, at = 0, attack = 0.005, wet = 0, lp0, lp1 = lp0, q = 0.7, detune = 0 }) {
  const t = ctx.currentTime + at, o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type; o.detune.value = detune;
  o.frequency.setValueAtTime(f0, t);
  if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + dur);
  let node = o;
  if (lp0) {
    const f = ctx.createBiquadFilter();
    f.type = 'lowpass'; f.Q.value = q;
    f.frequency.setValueAtTime(lp0, t);
    if (lp1 !== lp0) f.frequency.exponentialRampToValueAtTime(Math.max(20, lp1), t + dur);
    node = o.connect(f);
  }
  env(g, t, gain, attack, dur);
  out(node.connect(g), wet);
  o.start(t); o.stop(t + dur + 0.05);
}
// Filtered noise, optionally sweeping the filter.
function noise({ type = 'bandpass', f0 = 1000, f1 = f0, q = 0.8, dur = 0.1, gain = 0.2, at = 0, attack = 0.003, wet = 0 }) {
  const t = ctx.currentTime + at, s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
  s.buffer = noiseBuf; s.loop = true;
  f.type = type; f.Q.value = q;
  f.frequency.setValueAtTime(f0, t);
  if (f1 !== f0) f.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
  env(g, t, gain, attack, dur);
  out(s.connect(f).connect(g), wet);
  s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05);
}
// Weight you feel more than hear.
const thump = (f = 70, gain = 0.3, dur = 0.18, at = 0) => tone({ f0: f, f1: f * 0.55, dur, gain, at, attack: 0.004 });

const SOUNDS = {
  // Controls: soft, dry, short.
  click() { noise({ f0: 2400, q: 1.2, dur: 0.012, gain: 0.07 }); thump(110, 0.09, 0.06); },
  key() { noise({ f0: 1900 + Math.random() * 900, q: 1.5, dur: 0.01, gain: 0.035 }); },
  tick() { noise({ type: 'highpass', f0: 4200, dur: 0.008, gain: 0.025 }); },
  on() { thump(130, 0.16, 0.09); noise({ type: 'lowpass', f0: 1800, dur: 0.02, gain: 0.08 }); },
  off() { thump(95, 0.14, 0.09); noise({ type: 'lowpass', f0: 1100, dur: 0.02, gain: 0.07 }); },
  panel() { noise({ f0: 180, f1: 1400, q: 0.6, dur: 0.38, gain: 0.07, attack: 0.12, wet: 0.35 }); thump(60, 0.12, 0.25, 0.08); },
  send() { thump(72, 0.26, 0.32); noise({ f0: 500, f1: 2600, q: 0.5, dur: 0.22, gain: 0.05, attack: 0.05, wet: 0.3 }); },
  // ULTRON's state: low resonant tones, like a large machine taking notice.
  listen() { tone({ f0: 146.8, dur: 0.9, gain: 0.08, attack: 0.05, wet: 0.5 }); tone({ f0: 220, dur: 0.8, gain: 0.05, attack: 0.08, wet: 0.5, at: 0.05 }); },
  listenEnd() { tone({ f0: 220, dur: 0.6, gain: 0.05, attack: 0.03, wet: 0.4 }); tone({ f0: 146.8, dur: 0.75, gain: 0.07, attack: 0.05, wet: 0.4, at: 0.07 }); },
  think() { thump(48, 0.22, 0.4); },
  action() { tone({ f0: 660, dur: 0.5, gain: 0.03, attack: 0.002, wet: 0.7 }); tone({ f0: 660 * 2.76, dur: 0.25, gain: 0.012, attack: 0.002, wet: 0.7 }); },
  done() { tone({ f0: 196, dur: 0.9, gain: 0.07, attack: 0.03, wet: 0.5 }); tone({ f0: 293.7, dur: 0.85, gain: 0.05, attack: 0.05, wet: 0.5, at: 0.04 }); },
  error() {
    tone({ type: 'sawtooth', f0: 98, dur: 0.7, gain: 0.08, attack: 0.02, lp0: 600, lp1: 180, wet: 0.4 });
    tone({ type: 'sawtooth', f0: 103.8, dur: 0.7, gain: 0.07, attack: 0.02, lp0: 600, lp1: 180, wet: 0.4 });
    thump(49, 0.22, 0.5);
  },
  alert() {
    for (const at of [0, 0.32]) tone({ type: 'sawtooth', f0: 110, dur: 0.28, gain: 0.07, at, attack: 0.01, lp0: 900, lp1: 220, wet: 0.35 });
    thump(55, 0.2, 0.4);
  },
  // Digital tearing: short grains of dark noise and sub.
  glitch(amount = 1) {
    const n = Math.round(3 + 6 * amount);
    for (let i = 0; i < n; i++) {
      const at = Math.random() * 0.2 * amount;
      if (Math.random() < 0.7) noise({ f0: 300 + Math.random() * 3200, q: 3, dur: 0.008 + Math.random() * 0.03, gain: 0.08 * amount, at, attack: 0.001 });
      else thump(40 + Math.random() * 40, 0.12 * amount, 0.04, at);
    }
  },

  // Start-up
  // The room: a low, slowly opening drone.
  drone(dur = 4) {
    const t = ctx.currentTime, f = ctx.createBiquadFilter(), g = ctx.createGain();
    f.type = 'lowpass'; f.Q.value = 4;
    f.frequency.setValueAtTime(70, t);
    f.frequency.exponentialRampToValueAtTime(700, t + dur * 0.85);
    env(g, t, 0.12, dur * 0.6, dur);
    for (const hz of [36.7, 36.9, 55, 73.4]) {
      const o = ctx.createOscillator();
      o.type = 'sawtooth'; o.frequency.value = hz;
      o.connect(f); o.start(t); o.stop(t + dur + 0.05);
    }
    out(f.connect(g), 0.4);
  },
  // The title hit: a huge low brass-like swell with an impact on top.
  braam() {
    for (const [hz, d] of [[41.2, 0], [41.2, 7], [61.7, -5], [82.4, 4]]) {
      tone({ type: 'sawtooth', f0: hz, dur: 3.4, gain: 0.09, attack: 0.04, lp0: 160, lp1: 90, q: 2, detune: d, wet: 0.5 });
      tone({ type: 'sawtooth', f0: hz, dur: 1.2, gain: 0.06, attack: 0.02, lp0: 1400, lp1: 120, q: 3, detune: -d, wet: 0.5 });
    }
    tone({ f0: 41.2, f1: 30, dur: 2.6, gain: 0.4, attack: 0.01 });
    noise({ type: 'lowpass', f0: 2600, f1: 120, dur: 0.7, gain: 0.22, attack: 0.002, wet: 0.6 });
  },
  boom() { tone({ f0: 62, f1: 28, dur: 1.6, gain: 0.45, attack: 0.006 }); noise({ type: 'lowpass', f0: 700, f1: 50, dur: 0.9, gain: 0.2, wet: 0.5 }); },
  // Particles gathering: a rising wash with a crystalline shimmer.
  riser(dur = 2.6) {
    noise({ f0: 160, f1: 5200, q: 1.1, dur, gain: 0.09, attack: dur * 0.85, wet: 0.5 });
    tone({ type: 'sawtooth', f0: 55, f1: 110, dur, gain: 0.05, attack: dur * 0.8, lp0: 120, lp1: 900, wet: 0.4 });
    for (let i = 0; i < 26; i++) {
      tone({ f0: 1800 + Math.random() * 3600, dur: 0.18 + Math.random() * 0.3, gain: 0.004 + Math.random() * 0.006, at: (i / 26) * dur * 0.95, attack: 0.02, wet: 0.9 });
    }
  },
  // The eyes lighting: a low resonant ignition.
  ignite() {
    tone({ type: 'sawtooth', f0: 55, f1: 82, dur: 1.4, gain: 0.1, attack: 0.03, lp0: 200, lp1: 1200, q: 6, wet: 0.5 });
    thump(58, 0.3, 0.6);
    noise({ f0: 1200, f1: 300, q: 2, dur: 0.6, gain: 0.05, attack: 0.01, wet: 0.6 });
  },
  wink() { noise({ f0: 900, q: 2, dur: 0.05, gain: 0.05, wet: 0.3 }); thump(90, 0.12, 0.12, 0.02); },
  dissolve() { noise({ f0: 3200, f1: 300, q: 0.8, dur: 1.2, gain: 0.07, attack: 0.05, wet: 0.7 }); },
  // A string cut: a dry snap and a low thud.
  snap() { noise({ type: 'highpass', f0: 2600, dur: 0.018, gain: 0.16, attack: 0.001 }); thump(85, 0.2, 0.22, 0.005); },
  // Hand-over to the interface.
  power() {
    tone({ type: 'sawtooth', f0: 41, f1: 82, dur: 1.1, gain: 0.09, attack: 0.4, lp0: 100, lp1: 1200, wet: 0.5 });
    noise({ f0: 200, f1: 2400, q: 0.7, dur: 1, gain: 0.06, attack: 0.7, wet: 0.5 });
    thump(55, 0.35, 0.6, 1);
  },
};

/** Play a sound by name: sfx('click'), sfx('glitch', 0.5)... Does nothing when sounds are off. */
export function sfx(name, ...args) {
  if (!enabled || !ready() || !SOUNDS[name]) return;
  try { SOUNDS[name](...args); } catch {}
}
/** Listening cues: functional feedback, so they play even with interface sounds switched off. */
export function cue(up = true) {
  if (!ready()) return;
  try { SOUNDS[up ? 'listen' : 'listenEnd'](); } catch {}
}
