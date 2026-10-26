/**
 * Read-only BATC QO-100 wideband FFT display, ported from HB9IIU's QOCAST (static/js/batc-spectrum.js).
 * Data format follows BATC's official web client: binary Uint16 FFT frames.
 *
 * Changes from QOCAST: no receiver tuning and no simulated signal (C3CAST has no receiver); amber instrument colours.
 *
 * Page hooks (same names as QOCAST):
 *   window.QO_ALLOWED_MHZ   - slot centres legal for the current SR (set by the page)
 *   window.QO_WIDE          - true at 1000 kS/s: both neighbouring slots must be free too
 *   window.QO_SR_KS         - the current symbol rate in kS/s (width of the chosen-slot band)
 *   window.QO_LOCKED        - true while on air: no frequency change
 *   window.onBatcSlotSelected(centerMhz) - called when a free, legal slot is clicked
 *   window.batcSetSelected(centerMhz|null), window.batcRedraw(), window.batcSlotState(centerMhz) -> true (occupied) | false | null
 */
(function () {
  'use strict';

  const FFT_URL = 'wss://eshail.batc.org.uk/wb/fft';
  const FFT_PROTOCOL = 'fft';
  const START_MHZ = 10490.5;
  const END_MHZ = 10499.5;
  const DISPLAY_FLOOR = 0.12;
  const DISPLAY_CEILING = 0.58;
  const CHANNEL_CENTERS = Array.from({ length: 14 }, (_, index) => 10492.75 + index * 0.5);
  const canvas = document.querySelector('#spectrum');
  const status = document.querySelector('#specChip');
  const FONT = 'ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace';

  // instrument colours (the page's amber / green / red)
  const AMBER = '#f0a52c';
  const OK = '#3ecf8e';
  const BAD = '#ef5350';
  const GRID = 'rgba(108, 122, 136, .28)';
  const LABEL = '#6c7a88';

  const same = (a, b) => Math.abs(a - b) < 0.001;

  function slotAllowed(center) {
    return (window.QO_ALLOWED_MHZ || []).some((mhz) => same(mhz, center));
  }

  // A slot can be chosen when it is legal and everything it occupies is free.
  function slotSelectable(center) {
    if (!slotAllowed(center)) return false;
    const needed = window.QO_WIDE ? [center - 0.5, center, center + 0.5] : [center];
    return needed.every((mhz) => {
      for (const [slot, active] of slotStates) if (same(slot, mhz)) return active === false;
      return false;
    });
  }

  if (!canvas || !status) return;

  const context = canvas.getContext('2d');
  let socket = null;
  let reconnectTimer = null;
  let latestFrame = null;
  let renderPending = false;
  let intentionallyClosed = false;
  let slotStates = new Map();
  let selectedCenter = null;

  const CHIP = { success: 'ok', danger: 'bad', secondary: '' };
  function setStatus(label, style) {
    status.className = 'chip ' + (CHIP[style] || '');
    const text = document.querySelector('#specChipText');
    if (text) text.textContent = label.toLowerCase();
  }

  function canvasSize() {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(canvas.clientWidth));
    const height = Math.max(1, Math.floor(canvas.clientHeight));
    const pixelWidth = Math.floor(width * ratio);
    const pixelHeight = Math.floor(height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width, height };
  }

  function draw(frame) {
    const { width, height } = canvasSize();
    const top = 8;
    const bottom = height - 40;
    const plotHeight = bottom - top;

    context.clearRect(0, 0, width, height);
    context.strokeStyle = GRID;
    context.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = top + (plotHeight * i / 4);
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(width, y);
      context.stroke();
    }

    const labels = [10490.5, 10492.5, 10494.5, 10496.5, 10498.5, 10499.5];
    context.font = `10px ${FONT}`;
    context.fillStyle = LABEL;
    labels.forEach((frequency, index) => {
      const x = index * width / (labels.length - 1);
      context.beginPath();
      context.moveTo(x, top);
      context.lineTo(x, bottom);
      context.stroke();
      context.textAlign = index === 0 ? 'left' : (index === labels.length - 1 ? 'right' : 'center');
      context.fillText(`${frequency.toFixed(1)}${index === labels.length - 1 ? ' MHz' : ''}`, x, height - 6);
    });

    function frequencyX(frequency) {
      return (frequency - START_MHZ) * width / (END_MHZ - START_MHZ);
    }

    const channelSpacing = frequencyX(CHANNEL_CENTERS[1]) - frequencyX(CHANNEL_CENTERS[0]);
    const slotWidth = Math.max(6, channelSpacing * 0.62);
    let noiseFloor = null;
    let activityThreshold = null;
    if (frame && frame.length >= 2) {
      const sortedFrame = Array.from(frame).sort((a, b) => a - b);
      noiseFloor = sortedFrame[Math.floor(sortedFrame.length / 2)];

      const beaconStart = Math.floor((10490.8 - START_MHZ) * frame.length / (END_MHZ - START_MHZ));
      const beaconEnd = Math.ceil((10492.2 - START_MHZ) * frame.length / (END_MHZ - START_MHZ));
      const beaconSamples = Array.from(frame.slice(beaconStart, beaconEnd)).sort((a, b) => a - b);
      const beaconLevel = beaconSamples[Math.floor(beaconSamples.length / 2)];
      activityThreshold = noiseFloor + (beaconLevel - noiseFloor) * 0.5;
    }

    function slotHasTransmission(center) {
      if (activityThreshold === null) return null;
      const startIndex = Math.max(0, Math.floor((center - 0.2 - START_MHZ) * frame.length / (END_MHZ - START_MHZ)));
      const endIndex = Math.min(frame.length, Math.ceil((center + 0.2 - START_MHZ) * frame.length / (END_MHZ - START_MHZ)));
      const samples = Array.from(frame.slice(startIndex, endIndex)).sort((a, b) => a - b);
      const upperQuartile = samples[Math.floor(samples.length * 0.75)];
      return upperQuartile > activityThreshold;
    }

    slotStates = new Map();
    CHANNEL_CENTERS.forEach((center) => slotStates.set(center, slotHasTransmission(center)));
    CHANNEL_CENTERS.forEach((center) => {
      const active = slotStates.get(center);
      if (!slotAllowed(center)) context.fillStyle = '#2a343d';
      else if (active === null) context.fillStyle = '#5d6b78';
      else context.fillStyle = slotSelectable(center) ? OK : BAD;
      context.fillRect(frequencyX(center) - slotWidth / 2, bottom + 8, slotWidth, 6);
      if (selectedCenter !== null && same(center, selectedCenter)) {
        context.strokeStyle = '#ffffff';
        context.lineWidth = 2;
        context.strokeRect(frequencyX(center) - slotWidth / 2 - 2, bottom + 6, slotWidth + 4, 10);
      }
    });
    context.fillStyle = LABEL;
    context.textAlign = 'left';
    context.font = `9px ${FONT}`;
    context.fillText('500 kHz slots', 4, bottom + 24);

    // The chosen frequency: a semi-transparent band over the plot, as wide as our
    // signal (symbol rate x 1.35), under the trace so the spectrum stays visible.
    if (selectedCenter !== null) {
      const sr = window.QO_SR_KS || 333;
      const halfMhz = sr * 1.35 / 1000 / 2;
      const left = frequencyX(selectedCenter - halfMhz);
      const right = frequencyX(selectedCenter + halfMhz);
      context.fillStyle = 'rgba(240, 165, 44, .22)';
      context.fillRect(left, top, right - left, plotHeight);
      context.strokeStyle = 'rgba(240, 165, 44, .85)';
      context.lineWidth = 1;
      context.strokeRect(left + .5, top + .5, right - left - 1, plotHeight - 1);
    }

    if (!frame || frame.length < 2) {
      context.fillStyle = LABEL;
      context.textAlign = 'center';
      context.font = `11px ${FONT}`;
      context.fillText('waiting for BATC spectrum data', width / 2, height / 2 - 8);
      return;
    }

    const points = [];
    for (let x = 0; x < width; x += 1) {
      const sourceIndex = x * (frame.length - 1) / Math.max(1, width - 1);
      const left = Math.floor(sourceIndex);
      const fraction = sourceIndex - left;
      const sample = frame[left] + fraction * (frame[Math.min(left + 1, frame.length - 1)] - frame[left]);
      const normalized = Math.max(0, Math.min(
        1,
        (sample / 65535 - DISPLAY_FLOOR) / (DISPLAY_CEILING - DISPLAY_FLOOR)
      ));
      points.push([x, bottom - normalized * plotHeight]);
    }

    const gradient = context.createLinearGradient(0, top, 0, bottom);
    gradient.addColorStop(0, 'rgba(240, 165, 44, .58)');
    gradient.addColorStop(1, 'rgba(240, 165, 44, .03)');
    context.beginPath();
    context.moveTo(points[0][0], bottom);
    points.forEach((point) => context.lineTo(point[0], point[1]));
    context.lineTo(points[points.length - 1][0], bottom);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();

    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(point[0], point[1]);
      else context.lineTo(point[0], point[1]);
    });
    context.strokeStyle = AMBER;
    context.lineWidth = 1.5;
    context.stroke();
  }

  function scheduleDraw(frame) {
    latestFrame = frame;
    if (renderPending) return;
    renderPending = true;
    window.requestAnimationFrame(() => {
      renderPending = false;
      draw(latestFrame);
    });
  }

  function connect() {
    if (document.hidden || socket) return;
    intentionallyClosed = false;
    setStatus('CONNECTING', 'secondary');

    try {
      socket = new WebSocket(FFT_URL, FFT_PROTOCOL);
      socket.binaryType = 'arraybuffer';
    } catch (_error) {
      socket = null;
      scheduleReconnect();
      return;
    }

    socket.addEventListener('open', () => setStatus('LIVE', 'success'));
    socket.addEventListener('message', (event) => {
      if (event.data instanceof ArrayBuffer) {
        scheduleDraw(new Uint16Array(event.data));
      }
    });
    socket.addEventListener('close', () => {
      socket = null;
      if (!intentionallyClosed) scheduleReconnect();
    });
    socket.addEventListener('error', () => setStatus('OFFLINE', 'danger'));
  }

  function scheduleReconnect() {
    setStatus('OFFLINE', 'danger');
    if (reconnectTimer || document.hidden) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 2000);
  }

  function disconnect() {
    intentionallyClosed = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (socket) socket.close();
    socket = null;
    setStatus('PAUSED', 'secondary');
  }

  canvas.addEventListener('click', (event) => {
    if (window.QO_LOCKED) return;   // no frequency change while on air
    const rectangle = canvas.getBoundingClientRect();
    const x = event.clientX - rectangle.left;
    const y = event.clientY - rectangle.top;
    const slotY = canvas.clientHeight - 32;
    if (Math.abs(y - slotY) > 10) return;

    const clickedFrequency = START_MHZ + x * (END_MHZ - START_MHZ) / canvas.clientWidth;
    const center = CHANNEL_CENTERS.reduce((closest, candidate) => (
      Math.abs(candidate - clickedFrequency) < Math.abs(closest - clickedFrequency) ? candidate : closest
    ));
    const spacingPixels = 0.5 * canvas.clientWidth / (END_MHZ - START_MHZ);
    const centerPixels = (center - START_MHZ) * canvas.clientWidth / (END_MHZ - START_MHZ);
    if (Math.abs(x - centerPixels) > spacingPixels * 0.31 || !slotSelectable(center)) return;

    selectedCenter = center;
    if (window.onBatcSlotSelected) window.onBatcSlotSelected(center);
    draw(latestFrame);
  });

  canvas.addEventListener('mousemove', (event) => {
    const y = event.clientY - canvas.getBoundingClientRect().top;
    const overSlots = Math.abs(y - (canvas.clientHeight - 32)) <= 10;
    canvas.style.cursor = overSlots && !window.QO_LOCKED ? 'pointer' : 'default';
  });
  canvas.title = 'Click a green slot to choose your TX frequency (green: free, red: occupied, grey: not allowed at this symbol rate)';

  window.batcSetSelected = (center) => { selectedCenter = center; draw(latestFrame); };
  window.batcRedraw = () => draw(latestFrame);
  window.batcSlotState = (center) => { for (const [slot, active] of slotStates) if (same(slot, center)) return active; return null; };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) disconnect();
    else connect();
  });
  window.addEventListener('resize', () => draw(latestFrame));
  window.addEventListener('pagehide', disconnect);

  draw(null);
  connect();
}());
