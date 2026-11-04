/**
 * Receive-only BATC QO-100 wideband spectrum with click-to-tune.
 * Adapted from the QOCAST display (imported/qocast/batc-spectrum.js, HB9IIU): same BATC
 * FFT feed (binary Uint16 frames) and auto scale, without transmit slots or QOCAST APIs.
 * Carrier finding is DatvSignalFinder (signal-finder.js). A click calls window.onSignalChosen.
 */
(function () {
  'use strict';
  const FFT_URL = 'wss://eshail.batc.org.uk/wb/fft', FFT_PROTOCOL = 'fft';
  const START_MHZ = 10490.5, END_MHZ = 10499.5;
  const UNITS_PER_DB = 3276.8, SPAN_DB = 10.5, PLATEAU_AT = 0.90, SMOOTH_S = 10;
  const canvas = document.querySelector('#spectrum'), status = document.querySelector('#spectrum-status');
  const context = canvas.getContext('2d');
  let socket = null, reconnectTimer = null, latestFrame = null, renderPending = false, closing = false;
  let scaleFloor = 0.12, scaleCeiling = 0.58, smoothPlateau = null, smoothAt = 0;
  let tuned = null, message = '', messageTimer = null, slotState = 'searching';
  // Tuned signal: fill colour (RGB) and trace colour for searching, locked and lost.
  const SLOT_COLORS = { searching: ['58, 150, 255', '#8cc4ff'], locked: ['37, 194, 110', '#50d7a0'], lost: ['230, 70, 70', '#ff8a8a'] };

  const setStatus = (text) => { status.textContent = text; };
  const frequencyX = (mhz, width) => (mhz - START_MHZ) * width / (END_MHZ - START_MHZ);

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(canvas.clientWidth)), height = Math.max(1, Math.floor(canvas.clientHeight));
    if (canvas.width !== Math.floor(width * ratio) || canvas.height !== Math.floor(height * ratio)) {
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width, height };
  }

  // Keep the beacon plateau at a fixed height whatever gain the BATC receiver has.
  function updateScale(frame) {
    const sorted = Array.from(frame).sort((a, b) => a - b);
    const noise = sorted[Math.floor(sorted.length / 2)];
    const from = Math.floor((10490.8 - START_MHZ) * frame.length / (END_MHZ - START_MHZ));
    const to = Math.ceil((10492.2 - START_MHZ) * frame.length / (END_MHZ - START_MHZ));
    const beacon = Array.from(frame.slice(from, to)).sort((a, b) => a - b);
    const plateau = beacon[Math.floor(beacon.length * 0.75)];
    if (plateau - noise <= 2 * UNITS_PER_DB) return;     // no beacon: keep the last scale
    const now = performance.now();
    const keep = smoothPlateau === null ? 0 : Math.exp(-(now - smoothAt) / 1000 / SMOOTH_S);
    smoothPlateau = smoothPlateau === null ? plateau : plateau + (smoothPlateau - plateau) * keep;
    smoothAt = now;
    const span = SPAN_DB * UNITS_PER_DB;
    scaleFloor = Math.max(0, smoothPlateau - PLATEAU_AT * span) / 65535;
    scaleCeiling = scaleFloor + span / 65535;
  }

  function draw(frame) {
    const { width, height } = size();
    const top = 10, bottom = height - 22, plotHeight = bottom - top;
    context.clearRect(0, 0, width, height);
    context.strokeStyle = 'rgba(127, 151, 169, .20)';
    context.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = top + plotHeight * i / 4;
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
    }
    const labels = [10490.5, 10492.5, 10494.5, 10496.5, 10498.5, 10499.5];
    context.font = '10px system-ui, sans-serif';
    context.fillStyle = '#8193a1';
    labels.forEach((mhz, index) => {
      const x = index * width / (labels.length - 1);
      context.beginPath(); context.moveTo(x, top); context.lineTo(x, bottom); context.stroke();
      context.textAlign = index === 0 ? 'left' : (index === labels.length - 1 ? 'right' : 'center');
      context.fillText(mhz.toFixed(1) + (index === labels.length - 1 ? ' MHz' : ''), x, height - 7);
    });
    // The tuned signal is not boxed: its own trace is filled in its status colour (as in the DATVision player).
    let band = null;
    if (tuned) {
      const half = tuned.sr * 1.35 / 1000 / 2;      // occupied bandwidth
      band = [frequencyX(tuned.centerMhz - half, width), frequencyX(tuned.centerMhz + half, width)];
    }
    const [fill, trace] = SLOT_COLORS[slotState];
    if (!frame || frame.length < 2) {
      if (band) { context.fillStyle = `rgba(${fill}, .235)`; context.fillRect(band[0], 0, band[1] - band[0], bottom); }
      context.fillStyle = '#91a4b5'; context.textAlign = 'center';
      context.font = '12px system-ui, sans-serif';
      context.fillText('Waiting for BATC spectrum data…', width / 2, height / 2);
      return;
    }
    updateScale(frame);
    const points = [];
    for (let x = 0; x < width; x += 1) {
      const source = x * (frame.length - 1) / Math.max(1, width - 1);
      const left = Math.floor(source);
      const sample = frame[left] + (source - left) * (frame[Math.min(left + 1, frame.length - 1)] - frame[left]);
      const level = Math.max(0, Math.min(1, (sample / 65535 - scaleFloor) / (scaleCeiling - scaleFloor)));
      points.push([x, bottom - level * plotHeight]);
    }
    const gradient = context.createLinearGradient(0, top, 0, bottom);
    gradient.addColorStop(0, 'rgba(255, 212, 59, .62)');
    gradient.addColorStop(1, 'rgba(255, 212, 59, .03)');
    context.beginPath();
    context.moveTo(points[0][0], bottom);
    points.forEach((p) => context.lineTo(p[0], p[1]));
    context.lineTo(points[points.length - 1][0], bottom);
    context.closePath();
    context.fillStyle = gradient; context.fill();
    context.beginPath();
    points.forEach((p, i) => (i ? context.lineTo(p[0], p[1]) : context.moveTo(p[0], p[1])));
    context.strokeStyle = '#ffd43b'; context.lineWidth = 1.5; context.stroke();
    if (band) {
      context.save();
      context.beginPath(); context.rect(band[0], 0, band[1] - band[0], bottom); context.clip();
      context.beginPath();
      context.moveTo(points[0][0], bottom);
      points.forEach((p) => context.lineTo(p[0], p[1]));
      context.lineTo(points[points.length - 1][0], bottom);
      context.closePath();
      // A fade like the yellow trace's, in the status colour: strong at the signal's top, thin at the base.
      const inside = points.filter((p) => p[0] >= band[0] && p[0] <= band[1]);
      const peakY = inside.length ? Math.min(...inside.map((p) => p[1])) : top;
      const fade = context.createLinearGradient(0, peakY, 0, bottom);
      fade.addColorStop(0, `rgba(${fill}, .85)`);
      fade.addColorStop(0.55, `rgba(${fill}, .38)`);
      fade.addColorStop(1, `rgba(${fill}, .08)`);
      context.fillStyle = fade; context.fill();
      context.beginPath();
      points.forEach((p, i) => (i ? context.lineTo(p[0], p[1]) : context.moveTo(p[0], p[1])));
      context.strokeStyle = trace; context.lineWidth = 1.5;
      context.shadowColor = trace; context.shadowBlur = 8;          // a soft glow on the line
      context.stroke();
      context.restore();
    }
    if (message) {
      context.font = '12px system-ui, sans-serif'; context.textAlign = 'left';
      const w = context.measureText(message).width + 12;
      context.fillStyle = 'rgba(5, 20, 29, .88)'; context.fillRect(4, top + 4, w, 20);
      context.fillStyle = '#d6e3ec'; context.fillText(message, 10, top + 18);
    }
  }

  function scheduleDraw(frame) {
    latestFrame = frame;
    if (renderPending) return;
    renderPending = true;
    requestAnimationFrame(() => { renderPending = false; draw(latestFrame); });
  }

  function showMessage(text) {
    message = text;
    if (messageTimer) clearTimeout(messageTimer);
    messageTimer = setTimeout(() => { message = ''; draw(latestFrame); }, 4000);
    draw(latestFrame);
  }

  function connect() {
    if (document.hidden || socket) return;
    closing = false;
    setStatus('CONNECTING');
    try {
      socket = new WebSocket(FFT_URL, FFT_PROTOCOL);
      socket.binaryType = 'arraybuffer';
    } catch (_error) { socket = null; scheduleReconnect(); return; }
    socket.addEventListener('open', () => setStatus('LIVE'));
    socket.addEventListener('message', (event) => { if (event.data instanceof ArrayBuffer) scheduleDraw(new Uint16Array(event.data)); });
    socket.addEventListener('close', () => { socket = null; if (!closing) scheduleReconnect(); });
    socket.addEventListener('error', () => setStatus('DISCONNECTED'));
  }

  function scheduleReconnect() {
    setStatus('DISCONNECTED');
    if (reconnectTimer || document.hidden) return;
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, 2000);
  }

  function disconnect() {
    closing = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (socket) socket.close();
    socket = null;
    setStatus('PAUSED');
  }

  canvas.addEventListener('click', (event) => {
    const x = event.clientX - canvas.getBoundingClientRect().left;
    const mhz = START_MHZ + x * (END_MHZ - START_MHZ) / canvas.clientWidth;
    if (!latestFrame) return;
    const signal = DatvSignalFinder.findSignal(latestFrame, mhz);
    if (!signal) { showMessage('No signal at ' + mhz.toFixed(3) + ' MHz'); return; }
    window.onSignalChosen(signal);
  });
  canvas.style.cursor = 'crosshair';

  window.spectrumSetTuned = (signal) => { tuned = signal; slotState = 'searching'; draw(latestFrame); };
  window.spectrumSetState = (state) => { if (state !== slotState && SLOT_COLORS[state]) { slotState = state; draw(latestFrame); } };
  window.spectrumMessage = showMessage;
  document.addEventListener('visibilitychange', () => (document.hidden ? disconnect() : connect()));
  window.addEventListener('resize', () => draw(latestFrame));
  window.addEventListener('pagehide', disconnect);
  draw(null);
  connect();
}());
