/* Receiving is independent of TX. Only messages from our own receiver frames are accepted. */
(() => {
  const panels = [...document.querySelectorAll('[data-receiver]')];
  const requested = new Set();
  const pending = new Map();
  let activeReceiver = 1;
  let closing = false;
  function selectReceiver(number) {
    activeReceiver = number;
    for (const panel of panels) {
      const selected = Number(panel.dataset.receiver) === number;
      panel.classList.toggle('rx-selected', selected);
      panel.querySelector('.rx-pill').setAttribute('aria-pressed', String(selected));
    }
    document.getElementById('rxTargetLabel').textContent = `Receiver ${number}`;
  }
  selectReceiver(1);
  function tune(panel, signal) {
    const frame = panel.querySelector('iframe');
    if (!frame || !frame.dataset.ready) {
      pending.set(Number(panel.dataset.receiver), signal);
      if (!frame) start(panel);
      return;
    }
    send(panel, {type: 'tune', ...signal});
    panel.querySelector('.rx-message').textContent = 'Tuning…';
    window.c3ReceiverState?.(Number(panel.dataset.receiver), signal, 'searching', '');
  }
  function send(panel, message) {
    const frame = panel.querySelector('iframe');
    if (frame) frame.contentWindow.postMessage(message, new URL(frame.src).origin);
  }
  async function start(panel) {
    const n = Number(panel.dataset.receiver);
    requested.add(n);
    const message = panel.querySelector('.rx-message');
    try {
      const response = await fetch(`/api/receivers/${n}/start`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      message.textContent = 'Starting receiver…';
    } catch (error) {
      message.textContent = error.message;
      requested.delete(n);
    }
  }
  for (const panel of panels) {
    panel.querySelector('form').onsubmit = async event => {
      event.preventDefault();
      tune(panel, {centerMhz: Number(panel.querySelector('.rx-frequency').value), sr: Number(panel.querySelector('.rx-rate').value)});
    };
    panel.querySelector('.rx-pill').onclick = () => selectReceiver(Number(panel.dataset.receiver));
    panel.querySelector('.rx-stop').onclick = () => { pending.delete(Number(panel.dataset.receiver)); send(panel, {type: 'stop'}); };
    panel.querySelector('.rx-settings').onclick = () => send(panel, {type: 'settings'});
    panel.querySelector('.rx-full').onclick = () => panel.requestFullscreen().catch(() => {});
  }
  window.c3TuneReceiver = signal => {
    const number = activeReceiver;
    const panel = panels[number - 1];
    panel.querySelector('.rx-frequency').value = signal.centerMhz.toFixed(3);
    panel.querySelector('.rx-rate').value = signal.sr;
    tune(panel, signal);
  };
  window.addEventListener('message', event => {
    const panel = panels.find(p => p.querySelector('iframe')?.contentWindow === event.source);
    if (!panel || event.origin !== new URL(panel.querySelector('iframe').src).origin) return;
    if (event.data?.type === 'enlarge') panel.requestFullscreen().catch(() => {});
    if (event.data?.type === 'rx') {
      const data = event.data;
      window.c3ReceiverState?.(Number(panel.dataset.receiver), data.tuned, data.state, data.callsign);
      panel.querySelector('.rx-message').textContent = data.tuned
        ? `${data.callsign || ''} ${data.tuned.centerMhz.toFixed(3)} MHz · ${data.tuned.sr} kS/s · ${data.state}`
        : data.message || 'Ready · choose frequency and press Receive';
    }
  });
  async function poll() {
    if (closing) return;
    try {
      const response = await fetch('/api/receivers');
      const data = await response.json();
      for (const rx of data.receivers) {
        const panel = panels[rx.number - 1];
        panel.querySelector('.rx-device').textContent = rx.label;
        if (rx.available && !requested.has(rx.number)) await start(panel);
        if (rx.state === 'running' && !panel.querySelector('iframe')) {
          const frame = document.createElement('iframe');
          frame.src = `${rx.url}/embed?n=${rx.number}`;
          frame.title = `DATV receiver ${rx.number}`;
          frame.allow = 'autoplay; fullscreen';
          frame.addEventListener('load', () => {
            frame.dataset.ready = '1';
            const signal = pending.get(rx.number);
            if (signal) { pending.delete(rx.number); tune(panel, signal); }
          });
          panel.querySelector('.rx-picture').replaceChildren(frame);
        }
        if (rx.error) {
          const placeholder = document.createElement('div');
          placeholder.className = 'rx-placeholder';
          placeholder.textContent = 'Receiver stopped';
          panel.querySelector('.rx-picture').replaceChildren(placeholder);
          panel.querySelector('.rx-message').textContent = rx.error + ' · Press Receive to retry.';
        }
      }
    } catch (_) { /* A restarting app will answer the next poll. */ }
    setTimeout(poll, 3000);
  }
  window.addEventListener('pagehide', () => { closing = true; });
  poll();
})();
