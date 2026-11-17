/* Dev harness: dump a JSON description of the rendered board.
 * Appended to a copy of index.html (see README) so it runs after app.js.
 * Collection waits for `load`: app.js builds on DOMContentLoaded, and a script
 * at the end of <body> runs before that, so measuring earlier reads an empty
 * board. Everything reported is measured from the live DOM, never assumed. */
(() => {
  function collect() {
    const out = {
      vw: innerWidth, vh: innerHeight,
      overflow: document.documentElement.scrollWidth > innerWidth,
      vclip: [],
      offstage: [],
      panels: {},
      hub: null,
      deck: null,
      rail: null,
      strip: null,
      counts: {},
      clock: '',
      texts: {},
      errors: window.__errors || [],
    };

    const box = (el) => {
      const r = el.getBoundingClientRect();
      return {
        x: Math.round(r.left), y: Math.round(r.top),
        r: Math.round(r.right), b: Math.round(r.bottom),
        w: Math.round(r.width), h: Math.round(r.height),
      };
    };

    const hubEl = document.getElementById('hub');
    if (hubEl) out.hub = box(hubEl);
    if (document.querySelector('.deck')) out.deck = box(document.querySelector('.deck'));
    if (document.querySelector('.rail')) out.rail = box(document.querySelector('.rail'));
    if (document.querySelector('.topstrip')) out.strip = box(document.querySelector('.topstrip'));

    // Panels: local size plus the computed rotation, so the checker can rebuild
    // the rotated quad exactly.
    document.querySelectorAll('.panel').forEach((el) => {
      const cs = getComputedStyle(el);
      const m = new DOMMatrixReadOnly(cs.transform === 'none' ? undefined : cs.transform);
      const rot = Math.atan2(m.b, m.a) * 180 / Math.PI;
      const r = el.getBoundingClientRect();
      out.panels['.' + Array.from(el.classList).filter((c) => c.startsWith('panel--')).join('.')] = {
        ow: el.offsetWidth,
        oh: el.offsetHeight,
        rot: Math.round(rot * 10) / 10,
        cx: Math.round(r.left + r.width / 2),
        cy: Math.round(r.top + r.height / 2),
        opacity: Number(cs.opacity),
      };
    });

    // Leaf text that overflows its own box = a real legibility bug.
    const clip = [];
    document.querySelectorAll('.panel *').forEach((el) => {
      if (!el.textContent || !el.textContent.trim()) return;
      if (el.children.length) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      if (el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0) {
        clip.push({ t: el.textContent.trim().slice(0, 24), sh: el.scrollHeight, ch: el.clientHeight });
      }
    });
    out.vclip = clip.slice(0, 12);

    document.querySelectorAll('.panel, .rail, .deck, .topstrip').forEach((el) => {
      const b = box(el);
      if (b.r < 0 || b.b < 0 || b.x > innerWidth || b.y > innerHeight) {
        out.offstage.push({ cls: el.className, x: b.x, y: b.y, r: b.r, b: b.b });
      }
    });

    const count = (sel) => document.querySelectorAll(sel).length;
    out.counts = {
      panels: count('.panel'),
      segblocks: count('.segbar i'),
      segon: count('.segbar i.on'),
      gbars: count('.gbar'),
      hubbars: count('.hubbar'),
      ticks: count('.ticks line'),
      radar: count('.mr__blip'),
      reactor: count('.iris__seg'),
      segarcs: count('.segarc__fill'),
      callouts: count('.callout'),
      micro: count('.micro__t'),
    };

    const clock = document.getElementById('clock');
    out.clock = clock ? clock.textContent : '';
    ['#valCPU', '#valGPU', '#valMEM', '#gpuVal', '#coreVal', '#railCpuV', '#volPct1',
      '#deckTemp', '#deckUp', '#modeText', '#stripGpu', '#auxConns', '#usbState',
      '#fanCpu', '#tagFree', '#dialVal', '#deckClock', '#deckFree', '#railFoot']
      .forEach((s) => { const e = document.querySelector(s); out.texts[s] = e ? e.textContent : null; });

    // How much of the frame is actually inked (sanity that it is not blank).
    const pre = document.createElement('pre');
    pre.id = 'DIAGJSON';
    pre.textContent = JSON.stringify(out);
    document.body.appendChild(pre);
  }

  if (document.readyState === 'complete') {
    setTimeout(collect, 60);
  } else {
    window.addEventListener('load', () => setTimeout(collect, 60));
  }
})();
