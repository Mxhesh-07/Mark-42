// J.A.R.V.I.S.'s centrepiece: a holographic Earth (from the ULTRON shell).
// Continents are drawn as glowing points over a dark sphere, with a graticule, an atmosphere
// rim, orbiting satellites and signal arcs between cities. The globe swells with the voice,
// a waveform ring around it carries the audio, and a scan band sweeps it while she thinks.
// (Class name and API are unchanged from the old particle bubble, so app.js drives it as before.)

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { LAND_W, LAND_H, LAND_B64 } from './earth-data.js';

const DEG = Math.PI / 180;
// lat/lon (degrees) -> unit vector. North is +y; longitude 0 faces +x, 90°W faces the camera.
const geo = (lat, lon, r = 1) => new THREE.Vector3(
  Math.cos(lat * DEG) * Math.cos(lon * DEG) * r, Math.sin(lat * DEG) * r, -Math.cos(lat * DEG) * Math.sin(lon * DEG) * r);

const landBits = Uint8Array.from(atob(LAND_B64), c => c.charCodeAt(0));
function isLand(v) {
  const lat = Math.asin(v.y), lon = Math.atan2(-v.z, v.x);
  const x = Math.min(LAND_W - 1, Math.floor((lon / (2 * Math.PI) + 0.5) * LAND_W));
  const y = Math.min(LAND_H - 1, Math.floor((0.5 - lat / Math.PI) * LAND_H));
  const i = y * LAND_W + x;
  return (landBits[i >> 3] >> (i & 7)) & 1;
}

const CITIES = [
  [40.7, -74.0], [34.1, -118.2], [51.5, -0.1], [48.9, 2.4], [55.8, 37.6], [35.7, 139.7], [31.2, 121.5],
  [1.35, 103.8], [28.6, 77.2], [25.2, 55.3], [-33.9, 151.2], [-23.5, -46.6], [30.0, 31.2], [-26.2, 28.0],
  [42.66, 21.17], [37.6, 127.0], [19.4, -99.1], [64.1, -21.9],
];

const EARTH_VERT = /* glsl */ `
uniform float uTime, uLevel, uSpeak, uListen, uThink, uScale;
uniform sampler2D uFreq;
attribute vec3 aRand;
attribute float aLand;
varying float vAlpha;
varying float vHot;
void main(){
  vec3 d = position;
  float f = texture2D(uFreq, vec2(.02 + abs(d.y) * .42, .5)).r;
  float r = aLand > .5 ? 1.0 : .992;
  r += aLand * (.012 * aRand.x);                                   // a little relief on land
  r += uSpeak * f * (.05 + .06 * aLand);
  r += uListen * uLevel * .5 * (.5 + .5 * aRand.y);
  vec3 p = d * r;
  vec4 mv = modelViewMatrix * vec4(p, 1.);
  vec3 n = normalize(normalMatrix * d);
  float facing = dot(n, normalize(-mv.xyz));
  float rim = 1. - clamp(facing, 0., 1.);
  // Scan band: sweeps pole to pole while thinking.
  float sweep = fract(uTime * .45);
  float band = smoothstep(.09, 0., abs((d.y * .5 + .5) - sweep)) * uThink;
  float twinkle = .75 + .25 * sin(uTime * (1.5 + aRand.z * 3.) + aRand.x * 40.);
  vAlpha = (aLand > .5 ? (.55 + .45 * aRand.y) * twinkle : .1) * (.35 + 1.1 * pow(rim, 1.5) + .4 * facing);
  vAlpha *= smoothstep(-.05, .12, facing);                          // fade at the limb
  vHot = band * 1.6 + f * uSpeak * (.6 + aLand) + uListen * .25 * aLand;
  vAlpha += band * .5;
  float size = (aLand > .5 ? 1.25 + aRand.x * 1.1 : .9) + vHot * 1.6;
  gl_PointSize = size * uScale / -mv.z;
  gl_Position = projectionMatrix * mv;
}`;

const POINT_FRAG = /* glsl */ `
uniform vec3 uColA, uColB, uColC;
varying float vAlpha;
varying float vHot;
void main(){
  float d = length(gl_PointCoord - .5);
  float a = smoothstep(.5, .08, d) * vAlpha;
  if (a < .004) discard;
  vec3 col = mix(uColA, uColB, clamp(vAlpha * .9, 0., 1.));
  col = mix(col, uColC, clamp(vHot, 0., 1.) * .8);
  gl_FragColor = vec4(col * a, a);
}`;

const ATMO_VERT = /* glsl */ `
varying vec3 vN; varying vec3 vV;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.);
  vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const ATMO_FRAG = /* glsl */ `
uniform vec3 uColA, uColB; uniform float uPower, uGain;
varying vec3 vN; varying vec3 vV;
void main(){
  float f = pow(1. - abs(dot(vN, vV)), uPower) * uGain;
  gl_FragColor = vec4(mix(uColA, uColB, f) * f, f);
}`;

// Signal arcs: a bright pulse runs along each one.
const ARC_VERT = /* glsl */ `
attribute float aT; attribute float aSeed;
uniform float uTime;
varying float vA;
void main(){
  float head = fract(uTime * (.16 + aSeed * .12) + aSeed * 7.);
  float d = head - aT; if (d < 0.) d += 1.;
  vA = .1 + .9 * smoothstep(.32, 0., d);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.);
}`;
const ARC_FRAG = /* glsl */ `
uniform vec3 uColB, uColC; varying float vA;
void main(){ gl_FragColor = vec4(mix(uColB, uColC, vA * vA) * vA, vA); }`;

// The voice: a ring around the globe, pushed in and out by the live waveform.
const RING_VERT = /* glsl */ `
attribute float aU;
uniform sampler2D uWave; uniform float uSpeak, uListen, uLevel, uTime;
varying float vA;
void main(){
  float m = abs(aU * 2. - 1.);                                     // mirrored, so the ring closes cleanly
  float w = texture2D(uWave, vec2(m, .5)).r * 2. - 1.;
  float amp = uSpeak * .22 + uListen * .3;
  float r = 1.34 + w * amp + .004 * sin(aU * 120. + uTime * 3.);
  float a = aU * 6.2831853;
  vA = .16 + .84 * clamp(uSpeak + uListen, 0., 1.) * (.45 + abs(w) * 2.);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(cos(a) * r, sin(a) * r, 0., 1.);
}`;
const RING_FRAG = /* glsl */ `
uniform vec3 uColB, uColC; varying float vA;
void main(){ gl_FragColor = vec4(mix(uColB, uColC, clamp(vA - .3, 0., 1.)) * vA, vA); }`;

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x040608);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.group = new THREE.Group();          // mouse tilt + voice swell
    this.earth = new THREE.Group();          // axial tilt + spin
    this.earth.rotation.z = -23.4 * DEG;
    this.spin = new THREE.Group();
    this.spin.rotation.y = 1.9;              // open on the Atlantic
    this.earth.add(this.spin);
    this.group.add(this.earth);
    this.scene.add(this.group);

    this.waveData = new Uint8Array(256).fill(128);
    this.freqData = new Uint8Array(128);
    this.freqF = new Float32Array(128);
    const tex = data => {
      const t = new THREE.DataTexture(data, data.length, 1, THREE.RedFormat, THREE.UnsignedByteType);
      t.magFilter = t.minFilter = THREE.LinearFilter;
      t.needsUpdate = true;
      return t;
    };
    this.waveTex = tex(this.waveData);
    this.freqTex = tex(this.freqData);

    this.uniforms = {
      uTime: { value: 0 }, uLevel: { value: 0 }, uSpeak: { value: 0 },
      uListen: { value: 0 }, uThink: { value: 0 }, uScale: { value: 10 },
      uWave: { value: this.waveTex }, uFreq: { value: this.freqTex },
      uColA: { value: new THREE.Color(0.03, 0.28, 0.42) },   // deep reactor blue
      uColB: { value: new THREE.Color(0.22, 0.84, 1.0) },    // arc cyan
      uColC: { value: new THREE.Color(0.85, 0.98, 1.0) },    // white-hot
    };
    this.defaultColors = [this.uniforms.uColA.value.clone(), this.uniforms.uColB.value.clone(), this.uniforms.uColC.value.clone(), this.scene.background.clone()];

    this.buildEarth();
    this.buildOrbits();
    this.buildArcs();
    this.buildVoiceRing();
    this.buildStars();

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.85, 0.6, 0.1);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.mouse = { x: 0, y: 0 };
    this.tilt = { x: 0, y: 0 };
    this.slot = null;      // set to { x, y, r } to park the globe somewhere else (the Network module); null = its usual place
    this.moved = false;    // true on frames where the globe changed place, so the HUD around it can follow
    window.addEventListener('pointermove', e => {
      this.mouse.x = e.clientX / innerWidth - 0.5;
      this.mouse.y = e.clientY / innerHeight - 0.5;
    });
    window.addEventListener('resize', () => this.resize());
    this.resize();
  }

  shader(vert, frag, extra = {}) {
    return new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader: vert, fragmentShader: frag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...extra,
    });
  }

  buildEarth() {
    // Dark body: hides the far side, so the continents read as a solid planet.
    this.body = new THREE.Mesh(new THREE.SphereGeometry(0.985, 64, 48), new THREE.MeshBasicMaterial({ color: this.scene.background.clone() }));
    this.spin.add(this.body);

    const N = 52000, golden = Math.PI * (3 - Math.sqrt(5));
    const pos = [], rnd = [], land = [];
    const v = new THREE.Vector3();
    for (let i = 0; i < N; i++) {
      const y = 1 - ((i + 0.5) / N) * 2, r = Math.sqrt(1 - y * y), th = golden * i;
      v.set(Math.cos(th) * r, y, Math.sin(th) * r);
      const l = isLand(v);
      if (!l && i % 7) continue;                 // oceans: a sparse, faint lattice
      pos.push(v.x, v.y, v.z);
      rnd.push(Math.random(), Math.random(), Math.random());
      land.push(l);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('aRand', new THREE.Float32BufferAttribute(rnd, 3));
    g.setAttribute('aLand', new THREE.Float32BufferAttribute(land, 1));
    this.spin.add(new THREE.Points(g, this.shader(EARTH_VERT, POINT_FRAG)));

    // Graticule every 20°.
    const lines = [];
    for (let lat = -80; lat <= 80; lat += 20)
      for (let lon = -180; lon < 180; lon += 3) lines.push(geo(lat, lon, 1.002), geo(lat, lon + 3, 1.002));
    for (let lon = -180; lon < 180; lon += 20)
      for (let lat = -80; lat < 80; lat += 4) lines.push(geo(lat, lon, 1.002), geo(lat + 4, lon, 1.002));
    this.gratMat = new THREE.LineBasicMaterial({ color: this.uniforms.uColB.value.clone(), transparent: true, opacity: 0.11, blending: THREE.AdditiveBlending, depthWrite: false });
    this.spin.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(lines), this.gratMat));

    // Atmosphere: a thin bright limb and a wide soft halo.
    const atmo = (radius, power, gain, side) => new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 48), new THREE.ShaderMaterial({
      uniforms: { uColA: this.uniforms.uColA, uColB: this.uniforms.uColB, uPower: { value: power }, uGain: { value: gain } },
      vertexShader: ATMO_VERT, fragmentShader: ATMO_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side,
    }));
    this.group.add(atmo(1.0, 3.4, 0.6, THREE.FrontSide));
    this.halo = atmo(1.22, 4.5, 0.55, THREE.BackSide);
    this.group.add(this.halo);

    // Cities: steady beacons.
    const cg = new THREE.BufferGeometry().setFromPoints(CITIES.map(([la, lo]) => geo(la, lo, 1.012)));
    this.cityMat = new THREE.PointsMaterial({ color: this.uniforms.uColC.value.clone(), size: 0.03, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
    this.spin.add(new THREE.Points(cg, this.cityMat));
  }

  buildOrbits() {
    this.orbits = [];
    const circle = r => { const p = []; for (let i = 0; i <= 180; i++) p.push(new THREE.Vector3(Math.cos(i / 180 * 2 * Math.PI) * r, 0, Math.sin(i / 180 * 2 * Math.PI) * r)); return p; };
    for (const [r, tiltX, tiltZ, speed] of [[1.2, 1.15, 0.3, 0.5], [1.27, -0.5, 0.9, -0.34], [1.16, 0.2, -1.2, 0.72]]) {
      const o = new THREE.Group();
      o.rotation.set(tiltX, 0, tiltZ);
      const mat = new THREE.LineBasicMaterial({ color: this.uniforms.uColB.value.clone(), transparent: true, opacity: 0.2, blending: THREE.AdditiveBlending, depthWrite: false });
      o.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(circle(r)), mat));
      const sat = new THREE.Points(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(r, 0, 0)]),
        new THREE.PointsMaterial({ color: this.uniforms.uColC.value.clone(), size: 0.035, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      const pivot = new THREE.Group();
      pivot.add(sat);
      o.add(pivot);
      this.group.add(o);
      this.orbits.push({ pivot, speed, mat, satMat: sat.material });
    }
  }

  buildArcs() {
    const pos = [], t = [], seed = [];
    const pairs = [[0, 2], [2, 5], [1, 5], [3, 9], [9, 7], [7, 10], [0, 11], [4, 8], [12, 13], [14, 0], [6, 15], [16, 2], [17, 4]];
    const SEG = 48;
    pairs.forEach(([a, b], k) => {
      const A = geo(...CITIES[a]), B = geo(...CITIES[b]);
      const lift = 0.08 + A.angleTo(B) * 0.12;
      const s = Math.random();
      const at = u => new THREE.Vector3().copy(A).lerp(B, u).normalize().multiplyScalar(1.012 + Math.sin(u * Math.PI) * lift);
      for (let i = 0; i < SEG; i++) {
        const p = at(i / SEG), q = at((i + 1) / SEG);
        pos.push(p.x, p.y, p.z, q.x, q.y, q.z);
        t.push(i / SEG, (i + 1) / SEG);
        seed.push(s, s);
      }
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('aT', new THREE.Float32BufferAttribute(t, 1));
    g.setAttribute('aSeed', new THREE.Float32BufferAttribute(seed, 1));
    this.spin.add(new THREE.LineSegments(g, this.shader(ARC_VERT, ARC_FRAG)));
  }

  buildVoiceRing() {
    const N = 512, u = new Float32Array(N), pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) u[i] = i / N;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aU', new THREE.BufferAttribute(u, 1));
    this.voiceRing = new THREE.LineLoop(g, this.shader(RING_VERT, RING_FRAG));
    this.voiceRing.frustumCulled = false;
    this.scene.add(this.voiceRing);           // not in the tilting group: it always faces the viewer
  }

  buildStars() {
    const p = [];
    for (let i = 0; i < 700; i++) p.push(new THREE.Vector3().randomDirection().multiplyScalar(14 + Math.random() * 10));
    this.starMat = new THREE.PointsMaterial({ color: 0x8894a0, size: 0.05, transparent: true, opacity: 0.55, depthWrite: false });
    this.stars = new THREE.Points(new THREE.BufferGeometry().setFromPoints(p), this.starMat);
    this.scene.add(this.stars);
  }

  resize() {
    const w = innerWidth, h = innerHeight;
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.setSize(w, h);
    // Size the globe in pixels, then place the camera so it renders at that size.
    // Desktop: upper middle of the centre column, between the side panels, above the transcript.
    // Phones: smaller and higher, leaving room for the transcript.
    const phone = w < 860;
    const centre = phone ? w : w - 700;
    const rPx = phone ? Math.min(w * 0.25, h * 0.14, 110) : Math.max(96, Math.min(centre / 3.3, h * 0.185, 240));
    const offsetY = Math.round(h * (phone ? 0.17 : 0.15));
    this.camera.aspect = w / h;
    this.uniforms.uScale.value = (this.renderer.getPixelRatio() * h) / 130;
    this.home = { x: w / 2, y: h / 2 - offsetY, r: rPx };
    this.place(this.slot || this.home);
  }

  /** Put the globe's centre at screen pixel (x, y) with a radius of r pixels. */
  place({ x, y, r }) {
    const w = innerWidth, h = innerHeight, fov = THREE.MathUtils.degToRad(this.camera.fov);
    this.camera.position.z = 1 / (Math.tan(fov / 2) * (r / (h / 2)));
    this.camera.setViewOffset(w, h, w / 2 - x, h / 2 - y, w, h);
    this.camera.updateProjectionMatrix();
    this.screen = { x, y, r };
  }

  /** Recolour the globe: deep, mid and core colours plus the scene background (any CSS colour). */
  setColors(a, b, c, bg) {
    const u = this.uniforms;
    [u.uColA, u.uColB, u.uColC].forEach((uc, i) => { const col = [a, b, c][i]; if (col) uc.value.set(col); });
    if (bg) this.scene.background.set(bg);
    this.syncColors();
  }

  resetColors() {
    const [a, b, c, bg] = this.defaultColors;
    this.uniforms.uColA.value.copy(a); this.uniforms.uColB.value.copy(b); this.uniforms.uColC.value.copy(c);
    this.scene.background.copy(bg);
    this.syncColors();
  }

  syncColors() {
    const u = this.uniforms;
    this.body.material.color.copy(this.scene.background);
    this.gratMat.color.copy(u.uColB.value);
    this.cityMat.color.copy(u.uColC.value);
    for (const o of this.orbits) { o.mat.color.copy(u.uColB.value); o.satMat.color.copy(u.uColC.value); }
  }

  /** a = { wave: Uint8Array(256), freq: Uint8Array(128), level, speaking, listening, thinking } */
  update(dt, a) {
    const u = this.uniforms;
    u.uTime.value += dt;
    this.waveData.set(a.wave);
    for (let i = 0; i < 128; i++) { this.freqF[i] += (a.freq[i] - this.freqF[i]) * 0.35; this.freqData[i] = this.freqF[i]; }
    this.waveTex.needsUpdate = true;
    this.freqTex.needsUpdate = true;

    const ease = (cur, target, rate) => cur + (target - cur) * (1 - Math.exp(-dt * rate));
    u.uSpeak.value = ease(u.uSpeak.value, a.speaking ? 1 : 0, 3.2);
    u.uListen.value = ease(u.uListen.value, a.listening ? 1 : 0, 5);
    u.uThink.value = ease(u.uThink.value, a.thinking ? 1 : 0, 4);
    u.uLevel.value = ease(u.uLevel.value, a.level, 14);

    // Glide toward wherever the globe belongs right now.
    const to = this.slot || this.home, at = this.screen, k = 1 - Math.exp(-dt * 7);
    this.moved = Math.abs(to.x - at.x) + Math.abs(to.y - at.y) + Math.abs(to.r - at.r) > 0.25;
    if (this.moved) this.place({ x: at.x + (to.x - at.x) * k, y: at.y + (to.y - at.y) * k, r: at.r + (to.r - at.r) * k });

    this.spin.rotation.y += dt * (0.07 + u.uThink.value * 0.5);
    this.tilt.x = ease(this.tilt.x, this.mouse.y * 0.3, 2);
    this.tilt.y = ease(this.tilt.y, this.mouse.x * 0.4, 2);
    this.group.rotation.set(0.22 + this.tilt.x, this.tilt.y, 0);
    this.group.scale.setScalar(1 + u.uLevel.value * 0.1 + u.uListen.value * 0.02);
    for (const o of this.orbits) o.pivot.rotation.y += dt * o.speed * (1 + u.uThink.value * 2);
    this.cityMat.opacity = 0.65 + 0.35 * Math.sin(u.uTime.value * 2.4);
    this.halo.material.uniforms.uGain.value = 0.5 + u.uSpeak.value * 0.25 + u.uLevel.value * 1.2;
    this.stars.rotation.y += dt * 0.004;
    this.bloom.strength = 0.7 + u.uSpeak.value * 0.2 + u.uLevel.value * 0.6;
    this.composer.render(dt);
  }
}
