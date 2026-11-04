/* A page must own the server lease BEFORE any console or receiver script runs. */
(() => {
  const config = JSON.parse(document.getElementById('window-config').textContent);
  const code = document.getElementById('console-code').textContent;
  const originalFetch = window.fetch.bind(window);
  const token = crypto.randomUUID();
  let active = false, leaving = false, heartbeat = null, releaseLock = () => {};

  function blocked(message = 'Use the C3CAST window that is already open. This window has not started any players or changed reception.') {
    document.body.classList.remove('window-pending');
    const main = document.createElement('main'); main.className = 'window-blocked';
    const title = document.createElement('h1'); title.textContent = 'C3CAST is already open';
    const text = document.createElement('p'); text.textContent = message;
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn';
    retry.textContent = 'Try again'; retry.onclick = () => location.reload();
    main.append(title, text, retry); document.body.replaceChildren(main);
  }

  function load(name) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `/static/${name}?v=${encodeURIComponent(config.version)}`;
      script.onload = resolve; script.onerror = () => reject(new Error(`Could not load ${name}`));
      document.body.append(script);
    });
  }

  function release() {
    if (!active) return;
    active = false; leaving = true; clearInterval(heartbeat);
    navigator.sendBeacon('/api/bye', new Blob([JSON.stringify({window_token: token})], {type: 'application/json'}));
    releaseLock();
  }
  window.addEventListener('pagehide', release);
  window.addEventListener('pageshow', event => { if (event.persisted && leaving) location.reload(); });

  async function activate() {
    active = true;
    if (config.guarded) {
      window.fetch = (input, init = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin) return originalFetch(input, init);
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        headers.set('X-C3CAST-Window', token);
        return originalFetch(input, {...init, headers});
      };
      let pinging = false;
      heartbeat = setInterval(async () => {
        if (pinging || !active) return;
        pinging = true;
        try {
          const response = await window.fetch('/api/window/ping', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
          if (response.status === 409) location.reload();
        } catch (_) { /* The app's existing lifecycle handles a lost server. */ }
        finally { pinging = false; }
      }, 15000);
    }
    for (const name of config.before) await load(name);
    const script = document.createElement('script'); script.textContent = code; document.body.append(script);
    for (const name of config.after) await load(name);
    document.body.classList.remove('window-pending');
  }

  async function claim() {
    for (let attempt = 0; attempt < 4; attempt++) {
      const response = await originalFetch('/api/window/claim', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})});
      if (response.ok) return true;
      if (response.status !== 409) throw new Error('Cannot contact C3CAST');
      if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 250));
    }
    return false;
  }

  async function run() {
    if (!config.guarded) { await activate(); return; }
    const own = async lock => {
      if (!lock) { blocked(); return; }
      if (!await claim()) { blocked(); return; }
      await new Promise((resolve, reject) => {
        releaseLock = resolve;
        activate().catch(reject);
      });
    };
    if (navigator.locks) await navigator.locks.request('c3cast-console', {ifAvailable: true}, own);
    else await own(true);  // The server lease also protects different browsers.
  }
  run().catch(error => { release(); blocked(error.message + '. Reload this window to retry.'); });
})();
