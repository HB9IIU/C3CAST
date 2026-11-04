/** Carrier finder adapted from the local QOCAST spectrum by HB9IIU.
 * Standalone: no QOCAST process, DOM, network or module dependencies.
 * Width-based symbol rates are estimates; the receiver must confirm lock.
 * Same carrier measurement as QOCAST experimental's static/js/batc-spectrum.js.
 */
(function (scope) {
  'use strict';
  const START_MHZ = 10490.5, END_MHZ = 10499.5, BEACON_MHZ = 10491.5;
  const STANDARD_SRS = [25, 33, 50, 66, 125, 250, 333, 500, 1000, 1500, 2000];
  function smooth(frame) {
    const output = new Float64Array(frame.length);
    for (let index = 0; index < frame.length; index += 1) {
      let sum = 0, count = 0;
      for (let sample = Math.max(0, index - 3); sample <= Math.min(frame.length - 1, index + 3); sample += 1) {
        sum += frame[sample]; count += 1;
      }
      output[index] = sum / count;
    }
    return output;
  }

  function nearestSr(measured) {
    return STANDARD_SRS.reduce((best, value) =>
      Math.abs(Math.log(value / measured)) < Math.abs(Math.log(best / measured)) ? value : best);
  }

  function findSignal(frame, clickedMhz) {
    if (!frame || frame.length < 2 || !Number.isFinite(clickedMhz) || clickedMhz < START_MHZ || clickedMhz > END_MHZ) return null;
    const bins = frame.length;
    const mhzPerBin = (END_MHZ - START_MHZ) / (bins - 1);
    const values = smooth(frame);
    const sorted = Array.from(values).sort((a, b) => a - b);
    const noise = sorted[Math.floor(sorted.length / 2)];
    const clickedBin = Math.round((clickedMhz - START_MHZ) / mhzPerBin);
    const radius = Math.max(1, Math.round(0.1 / mhzPerBin));
    let peak = Math.max(0, clickedBin - radius);
    for (let index = peak; index <= Math.min(bins - 1, clickedBin + radius); index += 1) {
      if (values[index] > values[peak]) peak = index;
    }
    if (values[peak] - noise < 2000) return null;
    const halfPower = noise + (values[peak] - noise) / 2;
    let left = peak, right = peak;
    while (left > 0 && values[left - 1] > halfPower) left -= 1;
    while (right < bins - 1 && values[right + 1] > halfPower) right += 1;
    let centerMhz = START_MHZ + ((left + right) / 2) * mhzPerBin;
    let sr = nearestSr((right - left + 1) * mhzPerBin * 1000);
    if (Math.abs(centerMhz - BEACON_MHZ) < 0.3) { centerMhz = BEACON_MHZ; sr = 1500; }
    return { centerMhz, sr };
  }

  const api = {findSignal, START_MHZ, END_MHZ, BEACON_MHZ};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else scope.DatvSignalFinder = api;
}(globalThis));
