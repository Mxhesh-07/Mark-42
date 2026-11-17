/* ==========================================================================
   NEXUS // MAINFRAME HUD
   hud.js — boot sequencer + procedural animation drivers (vanilla JS)

   TIMING MAP (edit TIMING below to re-time the whole boot):
     0.0s  stage is black, every panel hidden
     0.5s  "powered"   → microchip + inner ring flicker on
     1.0s  "routing"   → circuit traces draw outward, rings fade in
     2.0s  "modules"   → panels blink online in a staggered random order
     3.8s  "complete"  → packets start flowing, boot caption fades out
   ========================================================================== */

(function () {
  "use strict";

  /* ------------------------------------------------------------------------
     1. CONFIG
     ------------------------------------------------------------------------ */
  var TIMING = {
    power: 500,
    routing: 1000,
    modules: 2000,
    complete: 3800
  };

  var stage = document.getElementById("stage");

  /* ------------------------------------------------------------------------
     2. UNIT SCALING
     The stylesheet sizes everything from --u / --v, which are 1% of the
     stage's rendered width / height. Recompute on resize.
     ------------------------------------------------------------------------ */
  function measure() {
    var rect = stage.getBoundingClientRect();
    if (!rect.width) return;
    stage.style.setProperty("--u", (rect.width / 100).toFixed(4) + "px");
    stage.style.setProperty("--v", (rect.height / 100).toFixed(4) + "px");
  }

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(measure).observe(stage);
  } else {
    window.addEventListener("resize", measure);
  }
  measure();

  /* ------------------------------------------------------------------------
     3. DOM BUILDERS
     Keeps the HTML readable: repeated cells/bars are generated here.
     ------------------------------------------------------------------------ */

  /* --- 3a. spectral analyser bars --- */
  var eqHost = document.getElementById("eqBars");
  var bars = [];

  function buildBars() {
    if (!eqHost) return;
    var count = parseInt(eqHost.dataset.bars, 10) || 18;
    for (var i = 0; i < count; i++) {
      var bar = document.createElement("i");
      var h = 14 + Math.random() * 76;
      bar.className = "bar";
      bar.style.setProperty("--h", h.toFixed(1) + "%");
      eqHost.appendChild(bar);
      bars.push(bar);
    }
  }

  /* --- 3b. keypad grids (columns x rows from data-grid="6x4") --- */
  function buildPads() {
    var pads = stage.querySelectorAll("[data-grid]");
    Array.prototype.forEach.call(pads, function (pad) {
      var parts = pad.dataset.grid.split("x");
      var cols = parseInt(parts[0], 10) || 4;
      var rows = parseInt(parts[1], 10) || 4;

      pad.style.gridTemplateColumns = "repeat(" + cols + ", 1fr)";
      pad.style.gridTemplateRows = "repeat(" + rows + ", 1fr)";

      for (var i = 0; i < cols * rows; i++) {
        var cell = document.createElement("span");
        cell.className = "cell";
        pad.appendChild(cell);
      }
    });
  }

  buildBars();
  buildPads();

  /* ------------------------------------------------------------------------
     4. BOOT SEQUENCE
     ------------------------------------------------------------------------ */
  var bootMsg = document.getElementById("bootMsg");

  function say(text) {
    if (bootMsg) bootMsg.textContent = text;
  }

  function boot() {
    say("COLD START");

    setTimeout(function () {
      stage.classList.add("powered");
      say("CORE POWER");
    }, TIMING.power);

    setTimeout(function () {
      stage.classList.add("routing");
      say("ROUTING CIRCUITS");
    }, TIMING.routing);

    setTimeout(function () {
      say("MODULES ONLINE");

      /* stagger panels: data-boot index * 70ms + jitter */
      var mods = stage.querySelectorAll(".mod");

      Array.prototype.forEach.call(mods, function (mod) {
        var order = parseInt(mod.dataset.boot, 10) || 0;
        var delay = order * 70 + Math.random() * 240;

        setTimeout(function () {
          mod.classList.add("live");
        }, delay);
      });
    }, TIMING.modules);

    setTimeout(function () {
      stage.classList.add("complete");
    }, TIMING.complete);
  }

  /* ------------------------------------------------------------------------
     5. LIVE ANIMATION DRIVERS
     ------------------------------------------------------------------------ */

  /* --- 5a. clock + uptime --- */
  var clockEl = document.getElementById("clock");
  var uptimeEl = document.getElementById("uptime");
  var t0 = Date.now();

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function tickClock() {
    var d = new Date();

    if (clockEl) {
      clockEl.textContent =
        pad2(d.getUTCHours()) + ":" +
        pad2(d.getUTCMinutes()) + ":" +
        pad2(d.getUTCSeconds()) + "Z";
    }

    if (uptimeEl) {
      var s = Math.floor((Date.now() - t0) / 1000);
      uptimeEl.textContent =
        pad2(Math.floor(s / 3600)) + ":" +
        pad2(Math.floor(s / 60) % 60) + ":" +
        pad2(s % 60);
    }
  }
  setInterval(tickClock, 1000);
  tickClock();

  /* --- 5b. equalizer: random smooth bar heights --- */
  setInterval(function () {
    var now = Date.now();
    for (var i = 0; i < bars.length; i++) {
      var wave = Math.abs(Math.sin(now / 700 + i * 0.42));
      var h = 12 + wave * 70 + Math.random() * 18;
      bars[i].style.setProperty("--h", Math.min(100, h).toFixed(1) + "%");
    }
  }, 190);

  /* --- 5c. keypads: random cells fade in/out --- */
  var pads = stage.querySelectorAll(".pad");

  function blinkCells() {
    Array.prototype.forEach.call(pads, function (pad) {
      var cells = pad.children;
      if (!cells.length) return;

      var hits = 1 + Math.floor(Math.random() * 3);

      for (var i = 0; i < hits; i++) {
        (function (cell) {
          if (!cell) return;
          cell.classList.add("hot");
          setTimeout(function () {
            cell.classList.remove("hot");
          }, 280 + Math.random() * 520);
        })(cells[Math.floor(Math.random() * cells.length)]);
      }
    });
  }
  setInterval(blinkCells, 420);

  /* --- 5d. circular gauges: drift the arc + the number --- */
  var gauges = stage.querySelectorAll(".gauge");

  Array.prototype.forEach.call(gauges, function (gauge) {
    var arc = gauge.querySelector(".g-val");
    var num = gauge.querySelector(".g-num");
    var value = parseFloat(gauge.dataset.gauge) || 50;

    function render(v) {
      v = Math.max(0, Math.min(100, v));
      value = v;
      if (arc) arc.style.strokeDashoffset = (100 - v).toFixed(1);
      if (num) num.textContent = Math.round(v);
    }

    render(value);

    setInterval(function () {
      render(value + (Math.random() - 0.5) * 14);
    }, 1200);
  });

  /* --- 5e. carrier waveform --- */
  var waveLine = document.getElementById("waveLine");
  var phase = 0;

  function drawWave() {
    if (!waveLine) return;

    var points = [];
    var steps = 48;

    for (var i = 0; i <= steps; i++) {
      var x = (i / steps) * 400;
      var envelope = Math.sin((i / steps) * Math.PI);
      var y =
        50 +
        Math.sin(i * 0.55 + phase) * 16 * envelope +
        (Math.random() - 0.5) * 12 * envelope;
      points.push(x.toFixed(1) + "," + y.toFixed(1));
    }

    waveLine.setAttribute("points", points.join(" "));
    phase += 0.55;
  }
  setInterval(drawWave, 110);
  drawWave();

  /* --- 5f. footer counters (cosmetic drift) --- */
  var fCpu = document.getElementById("fCpu");
  var fMem = document.getElementById("fMem");
  var cpu = 23;
  var mem = 41;

  setInterval(function () {
    cpu = Math.max(8, Math.min(88, cpu + (Math.random() - 0.5) * 9));
    mem = Math.max(20, Math.min(80, mem + (Math.random() - 0.5) * 5));

    if (fCpu) fCpu.textContent = Math.round(cpu) + "%";
    if (fMem) fMem.textContent = Math.round(mem) + "%";
  }, 1500);

  /* --- 5g. random flicker on one panel head (subtle texture) --- */
  setInterval(function () {
    var liveMods = stage.querySelectorAll(".mod.live");
    if (!liveMods.length) return;

    var pick = liveMods[Math.floor(Math.random() * liveMods.length)];
    pick.style.boxShadow = "inset 0 0 24px rgba(0,255,255,.16), 0 0 10px rgba(0,255,255,.22)";

    setTimeout(function () {
      pick.style.boxShadow = "";
    }, 90);
  }, 2600);

  /* ------------------------------------------------------------------------
     6. GO
     ------------------------------------------------------------------------ */
  if (document.readyState === "complete") {
    boot();
  } else {
    window.addEventListener("load", boot);
  }
})();
