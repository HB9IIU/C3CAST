/* Receiving is independent of TX. Only messages from our own receiver frames are accepted. */
(() => {
  const panels = [...document.querySelectorAll('[data-receiver]')];
  const requested = new Set();
  const available = new Set();
  const pending = new Map();
  const lastSignals = new Map();
  const eyes = new Map(panels.map(panel => [panel, new MagicEye(panel.querySelector('.rx-eye-display'), 76)]));
  let activeReceiver = 1;
  let closing = false;
  let popup = null;
  function closePopup() {
    if (!popup) return;
    const saved = popup; popup = null;
    saved.panel.classList.remove('rx-popup');
    saved.panel.removeAttribute('role'); saved.panel.removeAttribute('aria-modal'); saved.panel.removeAttribute('aria-label');
    saved.panel.querySelector('.rx-popup-close').classList.add('d-none');
    saved.panel.querySelector('.rx-full').classList.remove('d-none');
    saved.inert.forEach(([node, value]) => { node.inert = value; });
    saved.backdrop.remove(); saved.placeholder.remove();
    document.body.style.overflow = saved.overflow;
    saved.focus?.focus();
  }
  function openPopup(panel) {
    if (popup?.panel === panel) { closePopup(); return; }
    closePopup();
    const backdrop = document.createElement('div'); backdrop.className = 'rx-backdrop';
    backdrop.onclick = closePopup; document.body.append(backdrop);
    const placeholder = document.createElement('div');
    placeholder.style.height = `${panel.getBoundingClientRect().height}px`;
    panel.before(placeholder);
    const inert = [];
    for (let node = panel; node.parentElement && node !== document.body; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling === node || sibling === backdrop) continue;
        inert.push([sibling, sibling.inert]); sibling.inert = true;
      }
    }
    popup = {panel, backdrop, placeholder, inert, focus: document.activeElement, overflow: document.body.style.overflow};
    document.body.style.overflow = 'hidden';
    panel.classList.add('rx-popup'); panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', `Enlarged receiver ${panel.dataset.receiver}`);
    panel.querySelector('.rx-full').classList.add('d-none');
    const close = panel.querySelector('.rx-popup-close'); close.classList.remove('d-none'); close.focus();
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && popup) { event.preventDefault(); closePopup(); }
  });
  const second = panels[1];
  const hideSecond = second.querySelector('.rx-hide');
  const restoreSecond = document.querySelector('.rx-restore');
  function hideRx2(hidden) {
    second.classList.toggle('d-none', hidden);
    document.getElementById('receivers').classList.toggle('rx-single', hidden);
    restoreSecond.classList.toggle('d-none', !hidden);
    if (hidden && activeReceiver === 2) selectReceiver(1);
  }
  hideSecond.onclick = () => {
    if (!hideSecond.classList.contains('d-none')) {
      hideRx2(true);
      document.getElementById('showRx2').focus();
    }
  };
  document.getElementById('showRx2').onclick = () => {
    hideRx2(false);
    hideSecond.focus();
  };
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
    lastSignals.set(Number(panel.dataset.receiver), signal);
    panel.querySelector('[data-rx-field="tuning"]').textContent = `${signal.centerMhz.toFixed(3)} MHz · ${signal.sr} kS/s`;
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
    panel.querySelector('.rx-pill').onclick = () => selectReceiver(Number(panel.dataset.receiver));
    panel.querySelector('.rx-volume').oninput = event => {
      const volume = Number(event.target.value);
      send(panel, {type: 'audio', volume, muted: volume === 0});
    };
    panel.querySelector('.rx-mute').onclick = () => {
      send(panel, {type: 'audio', muted: panel.querySelector('.rx-mute').getAttribute('aria-pressed') !== 'true'});
    };
    panel.querySelector('.rx-retry').onclick = () => start(panel);
    panel.querySelector('.rx-settings').onclick = () => send(panel, {type: 'settings'});
    panel.querySelector('.rx-popup-close').onclick = closePopup;
    panel.querySelector('.rx-full').onclick = () => panel.requestFullscreen().catch(() => {});
  }
  window.c3MonitorTransmit = signal => {
    const panel = panels[0];
    if (!available.has(1) && !panel.querySelector('iframe')) return false;
    tune(panel, signal);
    return true; // Tune once per TX session; preserve the selected pill and RX2.
  };
  window.c3TuneReceiver = signal => {
    const number = activeReceiver;
    const panel = panels[number - 1];
    tune(panel, signal);
  };
  window.addEventListener('message', event => {
    const panel = panels.find(p => p.querySelector('iframe')?.contentWindow === event.source);
    if (!panel || event.origin !== new URL(panel.querySelector('iframe').src).origin) return;
    if (event.data?.type === 'audio') {
      const volume = Number(event.data.volume);
      if (!Number.isFinite(volume) || volume < 0 || volume > 1) return;
      const muted = Boolean(event.data.muted) || volume === 0;
      const slider = panel.querySelector('.rx-volume');
      slider.disabled = false;
      slider.value = volume;
      slider.style.setProperty('--fill', `${muted ? 0 : volume * 100}%`);
      const button = panel.querySelector('.rx-mute');
      button.disabled = false;
      button.setAttribute('aria-pressed', String(muted));
      button.setAttribute('aria-label', `${muted ? 'Unmute' : 'Mute'} receiver ${panel.dataset.receiver}`);
      button.querySelector('use').setAttribute('href', muted ? '#i-sound-off' : '#i-sound');
      panel.querySelector('.rx-audio').classList.toggle('muted', muted);
    }
    if (event.data?.type === 'enlarge') openPopup(panel);
    if (event.data?.type === 'close-enlarged' && popup?.panel === panel) closePopup();
    if (event.data?.type === 'rx') {
      const data = event.data;
      const info = data.info || {};
      const number = Number(panel.dataset.receiver);
      if (data.tuned) lastSignals.set(number, data.tuned);
      const signal = data.tuned || lastSignals.get(number);
      const set = (name, value) => { panel.querySelector(`[data-rx-field="${name}"]`).textContent = value || '—'; };
      const locked = info.locked === true || data.state === 'locked';
      set('station', locked ? [info.service || data.callsign, info.provider].filter(Boolean).join(' · ') : data.tuned ? 'Waiting for signal' : 'No stream');
      set('tuning', signal ? `${signal.centerMhz.toFixed(3)} MHz · ${signal.sr} kS/s` : '');
      set('video', locked ? [info.video, info.width && info.height ? `${info.width}×${info.height}` : ''].filter(Boolean).join(' · ') : '');
      set('audio', locked ? info.audio : '');
      set('mode', locked ? info.mode : '');
      set('quality', Number.isFinite(info.esn0) ? `${info.esn0_label || 'MER'} ${info.esn0.toFixed(1)} dB` : '');
      const badge = panel.querySelector('.rx-lock');
      badge.textContent = locked ? 'LOCKED' : data.state === 'lost' ? 'SIGNAL LOST' : data.tuned ? 'SEARCHING' : 'IDLE';
      badge.classList.toggle('locked', locked);
      const margin = locked && Number.isFinite(info.margin) ? info.margin : null;
      eyes.get(panel).update(margin, locked);
      panel.querySelector('.rx-margin').textContent = margin === null ? 'Margin —' : `Δ ${margin >= 0 ? '+' : ''}${margin.toFixed(1)} dB`;
      window.c3ReceiverState?.(Number(panel.dataset.receiver), data.tuned, data.state, data.callsign);
      panel.querySelector('.rx-message').textContent = '';
    }
  });
  async function poll() {
    if (closing) return;
    try {
      const response = await fetch('/api/receivers');
      const data = await response.json();
      for (const rx of data.receivers) {
        const panel = panels[rx.number - 1];
        if (rx.available) available.add(rx.number); else available.delete(rx.number);
        if (rx.number === 2) {
          const absent = !rx.available && rx.state !== 'running' && !rx.error && !panel.querySelector('iframe');
          hideSecond.classList.toggle('d-none', !absent);
          if (!absent) hideRx2(false);
        }
        panel.querySelector('.rx-retry').classList.toggle('d-none', !rx.error);
        panel.querySelector('.rx-device').textContent = rx.label;
        panel.querySelector('.rx-device').title = rx.label;
        if (rx.available && !requested.has(rx.number)) await start(panel);
        if (rx.state === 'running' && !panel.querySelector('iframe')) {
          const frame = document.createElement('iframe');
          frame.src = `${rx.url}/embed?n=${rx.number}&details=external`;
          frame.title = `DATV receiver ${rx.number}`;
          frame.allow = 'autoplay; fullscreen';
          frame.addEventListener('load', () => {
            frame.dataset.ready = '1';
            const signal = pending.get(rx.number);
            if (signal) { pending.delete(rx.number); tune(panel, signal); }
          });
          panel.querySelector('.rx-picture').replaceChildren(frame);
        }
        if (rx.state === 'starting') panel.querySelector('.rx-message').textContent = 'Checking receiver access and starting...';
        if (rx.error) {
          panel.querySelector('.rx-volume').disabled = true;
          panel.querySelector('.rx-mute').disabled = true;
          const placeholder = document.createElement('div');
          placeholder.className = 'rx-placeholder';
          placeholder.textContent = rx.state === 'unavailable' ? 'Receiver unavailable - possibly in use by another application' : 'Receiver stopped';
          panel.querySelector('.rx-picture').replaceChildren(placeholder);
          panel.querySelector('.rx-message').textContent = rx.error + (rx.state === 'unavailable' ? '' : ' · Click Retry to try again.');
        }
      }
    } catch (_) { /* A restarting app will answer the next poll. */ }
    setTimeout(poll, 3000);
  }
  window.addEventListener('pagehide', () => { closing = true; });
  poll();
})();
