/**
 * Constellation display: recent received symbols after carrier recovery, unit mean power,
 * +-1.5 full scale. Ported from the DATVision Pi player (ui/pi_player/panels.py, Constellation).
 *
 *   const view = new Constellation(parentElement);
 *   view.update(hexText, 'QPSK');   // datvrx "cells" payload: I then Q per symbol, byte = 128 + 64 x value
 *   view.update('', '');            // nothing received: shows the empty grid
 */
(function () {
  'use strict';
  const SIZE = 120;                  // same as the magic eye beside it

  class Constellation {
    constructor(parent) {
      this.canvas = document.createElement('canvas');
      this.canvas.style.cssText = `width:${SIZE}px;height:${SIZE}px;display:block`;
      this.canvas.setAttribute('role', 'img');
      this.canvas.setAttribute('aria-label', 'Constellation');
      this.canvas.title = 'Constellation: received symbols';
      parent.append(this.canvas);
      this.update('', '');
    }

    update(hex, modulation) {
      const points = [];
      for (let i = 0; i + 3 < hex.length; i += 4) {
        points.push([(parseInt(hex.substr(i, 2), 16) - 128) / 64, (parseInt(hex.substr(i + 2, 2), 16) - 128) / 64]);
      }
      this.draw(points, modulation);
    }

    draw(points, modulation) {
      const c = this.canvas, dpr = Math.min(2, window.devicePixelRatio || 1), pixels = Math.round(SIZE * dpr);
      if (c.width !== pixels) c.width = c.height = pixels;
      const g = c.getContext('2d');
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.fillStyle = '#05141d'; g.fillRect(0, 0, SIZE, SIZE);
      g.fillStyle = '#1d3647';
      g.fillRect(SIZE / 2, 0, 1, SIZE); g.fillRect(0, SIZE / 2, SIZE, 1);
      const at = (i, q) => [SIZE / 2 + i * SIZE / 3, SIZE / 2 - q * SIZE / 3];
      const rings = { QPSK: [4, Math.PI / 4], '8PSK': [8, 0] }[modulation];
      if (rings) {                       // where the symbols belong, as faint rings
        g.strokeStyle = '#5d7488'; g.lineWidth = 1;
        for (let k = 0; k < rings[0]; k += 1) {
          const angle = rings[1] + 2 * Math.PI * k / rings[0];
          const [x, y] = at(Math.cos(angle), Math.sin(angle));
          g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.stroke();
        }
      }
      g.fillStyle = 'rgba(80, 215, 160, .67)';
      for (const [i, q] of points) {
        const [x, y] = at(i, q);
        g.beginPath(); g.arc(x, y, 1.3, 0, Math.PI * 2); g.fill();
      }
    }
  }

  window.Constellation = Constellation;
})();
