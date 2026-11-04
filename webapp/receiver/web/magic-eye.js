/**
 * Magic Eye: an end-on view of an EM34 / 6E5-style tuning tube. Canvas port of the DATVision
 * player's eye (ui/pi_player/magic_eye.py and TuningEye in ui/DatvRx.Player/MonitorControls.cs),
 * which follows the OnAir receiver's eye after HB9IIU SDR-Tiouner and the Lynx DATV Receiver (G8YTZ).
 *
 * The two dark shadow wedges close as the margin above the decoding threshold grows: almost closed
 * at GOOD_MARGIN_DB or more, wide open when searching. The tube is cold (dark) when not running.
 *
 *   const eye = new MagicEye(parentElement, 120);
 *   eye.update(marginDb, running);   // margin in dB, or null when there is no lock
 *   // running defaults to "there is a margin"; pass true while searching to light the tube
 *
 * The original copy of the QOCAST eye is kept unchanged in imported/qocast/magic-eye.js.
 */
(function () {
  'use strict';

  const GOOD_MARGIN_DB = 5;
  const clamp = (x) => Math.max(0, Math.min(1, x));

  function seeded(seed) {                 // small deterministic generator: the ribs look the same every time
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function radial(g, x, y, radius, stops, fx = x, fy = y) {
    const gradient = g.createRadialGradient(fx, fy, 0, x, y, radius);
    for (const [position, color] of stops) gradient.addColorStop(position, color);
    return gradient;
  }

  // Qt-style conical gradient: angles run counter-clockwise from 3 o'clock, canvas runs clockwise.
  function conic(g, x, y, startDegrees, stops) {
    const gradient = g.createConicGradient(-startDegrees * Math.PI / 180, x, y);
    for (const [position, color] of stops) gradient.addColorStop(1 - position, color);
    return gradient;
  }

  const disc = (g, x, y, r) => { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); };
  const ringPath = (g, c, inner, outer) => {
    g.beginPath(); g.arc(c, c, outer, 0, Math.PI * 2); g.arc(c, c, inner, 0, Math.PI * 2, true);
  };

  class MagicEye {
    constructor(parent, size = 120) {
      this.size = size;
      this.dpr = Math.min(2, window.devicePixelRatio || 1);
      this.canvas = document.createElement('canvas');
      this.canvas.style.cssText = `width:${size}px;height:${size}px;display:block`;
      this.canvas.setAttribute('role', 'img');
      this.canvas.width = this.canvas.height = Math.round(size * this.dpr);
      parent.append(this.canvas);
      this.c = size / 2;
      this.outer = size * 0.40;           // edge of the fluorescent target
      this.cap = size * 0.155;            // black cap over the cathode
      this.value = this.target = 0;       // 0 widest shadow, 1 closed
      this.light = this.bright = 0;       // 0 cold tube, 1 lit
      this.frame = 0;
      this.last = 0;
      this.base = this.layer(this.paintBase);
      this.phosphor = this.layer(this.paintPhosphor);
      this.capLayer = this.layer(this.paintCap);
      this.glass = this.layer(this.paintGlass);
      this.update(null, false);
      this.render();
    }

    update(marginDb, running) {
      const valid = typeof marginDb === 'number' && Number.isFinite(marginDb);
      this.target = valid ? 0.12 + 0.88 * clamp(marginDb / GOOD_MARGIN_DB) : 0;
      this.bright = (running === undefined ? valid : running) ? 1 : 0;
      this.canvas.title = valid
        ? `Signal quality: D margin ${marginDb.toFixed(1)} dB above the decoding threshold`
        : (this.bright ? 'Searching: no lock yet' : 'No signal quality');
      this.canvas.setAttribute('aria-label', valid ? `Signal quality, D margin ${marginDb.toFixed(1)} dB` : 'Signal quality unavailable');
      this.wake();
    }

    wake() {
      if (this.frame) return;
      this.last = performance.now() - 33;
      this.frame = requestAnimationFrame((now) => this.tick(now));
    }

    tick(now) {
      this.frame = 0;
      if (!this.canvas.isConnected) return;
      if (now - this.last < 33) { this.frame = requestAnimationFrame((t) => this.tick(t)); return; }
      const dt = Math.min(0.1, (now - this.last) / 1000 || 0.033);
      this.last = now;
      // The shadow opens quickly when the signal drops and closes more slowly; the heater warms slowly.
      const follow = (current, goal, tau) => {
        const next = current + (goal - current) * (1 - Math.exp(-dt / tau));
        return Math.abs(goal - next) < 0.002 ? goal : next;
      };
      this.value = follow(this.value, this.target, this.target < this.value ? 0.10 : 0.22);
      this.light = follow(this.light, this.bright, 0.35);
      this.render();
      if (this.value !== this.target || this.light !== this.bright) this.frame = requestAnimationFrame((t) => this.tick(t));
    }

    // ---- static layers, rendered once
    layer(paint) {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = this.canvas.width;
      const g = canvas.getContext('2d');
      g.scale(this.dpr, this.dpr);
      paint.call(this, g);
      return canvas;
    }

    paintBase(g) {
      const c = this.c, s = this.size;
      // Mounting bezel: dark brushed metal.
      const grey = (v) => `rgb(${v},${v + 3},${v + 1})`;
      g.fillStyle = conic(g, c, c, 125, [[0, grey(0x5c)], [0.18, grey(0x22)], [0.42, grey(0x4a)], [0.6, grey(0x18)], [0.82, grey(0x3e)], [1, grey(0x5c)]]);
      disc(g, c, c, s * 0.495);
      g.fillStyle = '#030504';
      disc(g, c, c, s * 0.462);
      // Glass interior with the silvery getter deposit towards the rim.
      g.fillStyle = radial(g, c, c, s * 0.455, [[0, '#0c1510'], [0.8, '#050a07'], [0.93, 'rgb(58,56,48)'], [1, 'rgb(22,22,20)']]);
      disc(g, c, c, s * 0.455);
    }

    paintPhosphor(g) {
      const c = this.c, outer = this.outer, cap = this.cap, k = cap / outer, unit = this.size / 120;
      g.save();
      ringPath(g, c, cap * 0.9, outer);
      g.clip('evenodd');
      g.fillStyle = radial(g, c, c, outer, [[0, '#d6ffb0'], [k, '#c2ff9e'], [k + 0.14, '#7cff98'], [0.72, '#2ee874'], [0.9, '#0d9e48'], [1, '#043d1c']]);
      disc(g, c, c, outer);
      // Fine radial ribs of the target anode.
      const random = seeded(6), between = (a, b) => a + (b - a) * random();
      g.lineWidth = 0.7 * unit;
      for (let i = 0; i < 240; i += 1) {
        const angle = 2 * Math.PI * i / 240 + between(-0.01, 0.01);
        const light = random() < 0.45;
        g.strokeStyle = light ? `rgba(235,255,230,${between(14, 34) / 255})` : `rgba(0,45,18,${between(22, 55) / 255})`;
        const start = cap + between(0, 3) * unit;
        g.beginPath();
        g.moveTo(c + start * Math.cos(angle), c + start * Math.sin(angle));
        g.lineTo(c + outer * Math.cos(angle), c + outer * Math.sin(angle));
        g.stroke();
      }
      g.restore();
    }

    paintCap(g) {
      const c = this.c, cap = this.cap;
      g.fillStyle = radial(g, c, c, cap, [[0, '#2c312e'], [0.7, '#0d100e'], [1, '#020302']], c - cap * 0.35, c - cap * 0.4);
      disc(g, c, c, cap);
      g.fillStyle = conic(g, c, c, 135, [[0, 'rgba(190,200,195,.196)'], [0.12, 'rgba(190,200,195,0)'], [0.5, 'rgba(190,200,195,.086)'],
                                         [0.62, 'rgba(190,200,195,0)'], [1, 'rgba(190,200,195,.196)']]);
      disc(g, c, c, cap * 0.92);
    }

    paintGlass(g) {
      const c = this.c, s = this.size;
      // Curvature: the glass darkens towards its rim.
      g.fillStyle = radial(g, c, c, s * 0.455, [[0, 'rgba(0,0,0,0)'], [0.82, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,.47)']]);
      disc(g, c, c, s * 0.455);
      // Broad window reflection, top left.
      g.save();
      g.translate(c - s * 0.15, c - s * 0.19);
      g.scale(1, 0.19 / 0.24);
      g.fillStyle = radial(g, 0, 0, s * 0.24, [[0, 'rgba(255,255,255,.243)'], [1, 'rgba(255,255,255,0)']]);
      disc(g, 0, 0, s * 0.24);
      g.restore();
      // Small sharp highlight.
      g.save();
      g.translate(c - s * 0.2, c - s * 0.25);
      g.rotate(-38 * Math.PI / 180);
      g.scale(1, 0.028 / 0.065);
      g.fillStyle = radial(g, 0, 0, s * 0.065, [[0, 'rgba(255,255,255,.745)'], [1, 'rgba(255,255,255,0)']]);
      disc(g, 0, 0, s * 0.065);
      g.restore();
      // Faint crescent reflection along the lower right edge.
      g.strokeStyle = 'rgba(255,255,255,.133)';
      g.lineWidth = s * 0.012;
      g.lineCap = 'round';
      g.beginPath();
      g.arc(c, c, s * 0.42, 15 * Math.PI / 180, 70 * Math.PI / 180);
      g.stroke();
    }

    // The two dark wedges (top and bottom). Their soft edges fluoresce slightly brighter.
    shadow(g) {
      const half = 2 + (1 - this.value) * 48, soft = 5;
      const gradient = g.createConicGradient(0, this.c, this.c);
      for (let degree = 0; degree <= 360; degree += 1) {
        const distance = Math.min(Math.abs(degree - 90), Math.abs(degree - 270));
        let color;
        if (distance < half - soft / 2) color = 'rgba(3,24,11,.886)';
        else if (distance < half + soft / 2) {
          const t = (distance - (half - soft / 2)) / soft;
          color = `rgba(3,24,11,${0.886 * (1 - t * t * (3 - 2 * t))})`;
        } else if (distance < half + soft / 2 + 4) color = `rgba(215,255,205,${0.235 * (1 - (distance - half - soft / 2) / 4)})`;
        else color = 'rgba(0,0,0,0)';
        gradient.addColorStop(degree / 360, color);
      }
      return gradient;
    }

    render() {
      const g = this.canvas.getContext('2d'), c = this.c, outer = this.outer, cap = this.cap, light = this.light;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, this.canvas.width, this.canvas.height);
      g.drawImage(this.base, 0, 0);
      g.scale(this.dpr, this.dpr);
      if (light > 0.01) {
        g.globalAlpha = light;
        // Glow scattered in the glass around the target.
        g.fillStyle = radial(g, c, c, outer * 1.16, [[0, 'rgba(40,255,120,.353)'], [0.8, 'rgba(40,255,120,.353)'], [1, 'rgba(40,255,120,0)']]);
        disc(g, c, c, outer * 1.16);
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.drawImage(this.phosphor, 0, 0);
        g.scale(this.dpr, this.dpr);
        g.globalAlpha = 1;
        g.save();
        ringPath(g, c, cap * 0.9, outer + 1);
        g.clip('evenodd');
        g.fillStyle = this.shadow(g);
        disc(g, c, c, outer + 1);
        g.restore();
      }
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.drawImage(this.capLayer, 0, 0);
      g.scale(this.dpr, this.dpr);
      if (light > 0.01) {                 // green light reflected on the cap's edge
        g.strokeStyle = `rgba(110,255,150,${0.431 * light})`;
        g.lineWidth = 1.2;
        g.beginPath(); g.arc(c, c, cap - 0.6, 0, Math.PI * 2); g.stroke();
      }
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.drawImage(this.glass, 0, 0);
    }
  }

  window.MagicEye = MagicEye;
})();
