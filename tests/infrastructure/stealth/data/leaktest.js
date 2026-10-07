(async () => {
  const R = {};
  const put = (id, ok, detail) => { R[id] = { ok: !!ok, detail: detail === undefined ? '' : String(detail) }; };
  const safe = async (id, fn) => { try { await fn(); } catch (e) { put(id, false, 'EXC ' + (e && e.message)); } };
  const NATIVE = /^function (get |set )?[\w$]*\(\) \{ \[native code\] \}$/;

  // ---------- A. descriptor integrity ----------
  await safe('nav.ownProps', () => {
    const own = Object.getOwnPropertyNames(navigator);
    put('nav.ownProps', own.length === 0, JSON.stringify(own));
  });
  for (const p of ['platform', 'userAgent', 'hardwareConcurrency', 'deviceMemory', 'languages', 'language', 'webdriver', 'userAgentData', 'vendor', 'plugins', 'maxTouchPoints']) {
    await safe('desc.' + p, () => {
      const d = Object.getOwnPropertyDescriptor(Navigator.prototype, p);
      if (!d) { put('desc.' + p, false, 'no descriptor on Navigator.prototype'); return; }
      const g = d.get;
      const ts = Function.prototype.toString.call(g);
      const okTs = ts === `function get ${p}() { [native code] }` || ts === 'function () { [native code] }';
      const okName = g.name === 'get ' + p;
      const okProto = !g.hasOwnProperty('prototype');
      let okIllegal = false;
      try { g.call({}); } catch (e) { okIllegal = e instanceof TypeError && /Illegal invocation/.test(e.message); }
      put('desc.' + p, okTs && okName && okProto && okIllegal, JSON.stringify({ ts: ts.slice(0, 60), name: g.name, proto: !okProto, illegal: okIllegal }));
    });
  }
  await safe('screen.own', () => {
    const own = Object.getOwnPropertyNames(screen);
    put('screen.own', own.length === 0, JSON.stringify(own));
  });
  await safe('fn.toStringOfToString', () => {
    const s = Function.prototype.toString.call(Function.prototype.toString);
    put('fn.toStringOfToString', s === 'function toString() { [native code] }', s);
  });
  await safe('fn.toStringSelf', () => {
    const s = Function.prototype.toString.toString();
    put('fn.toStringSelf', s === 'function toString() { [native code] }', s);
  });
  await safe('webgl.fn', () => {
    const f = WebGLRenderingContext.prototype.getParameter;
    const ts = Function.prototype.toString.call(f);
    let illegal = false;
    try { f.call({}, 1); } catch (e) { illegal = e instanceof TypeError; }
    put('webgl.fn', (ts === 'function getParameter() { [native code] }' || ts === 'function () { [native code] }') && f.name === 'getParameter' && f.length === 1 && !f.hasOwnProperty('prototype') && illegal,
      JSON.stringify({ ts, name: f.name, len: f.length, illegal }));
  });
  await safe('canvas.fn', () => {
    const f = HTMLCanvasElement.prototype.toDataURL;
    const ts = Function.prototype.toString.call(f);
    put('canvas.fn', ts === 'function toDataURL() { [native code] }' || ts === 'function () { [native code] }', ts);
  });
  await safe('stack.leak', () => {
    let leaked = false;
    try {
      const d = Object.getOwnPropertyDescriptor(Navigator.prototype, 'platform').get;
      d.call(null);
    } catch (e) { leaked = /apply|Proxy|stealth|<anonymous>:\d+:\d+\)\s*\n\s*at Object/i.test(String(e.stack)); put('stack.leak', !leaked, e.stack.split('\n').slice(0, 4).join(' | ')); return; }
    put('stack.leak', false, 'getter.call(null) did not throw');
  });

  // ---------- D. automation / headless signals ----------
  await safe('auto.webdriver', () => put('auto.webdriver', navigator.webdriver === false, navigator.webdriver));
  await safe('auto.cdc', () => {
    const keys = Object.getOwnPropertyNames(window).filter(k => /^cdc_|^\$cdc_|__playwright|__pw_|__puppeteer|__nightmare|callPhantom|_phantom/i.test(k));
    put('auto.cdc', keys.length === 0, JSON.stringify(keys));
  });
  await safe('auto.chromeRuntime', () => {
    const c = window.chrome;
    put('auto.chromeRuntime', !!c && typeof c === 'object' && c.runtime === undefined, c ? Object.keys(c).join(',') + ' runtime=' + typeof c.runtime : 'no window.chrome');
  });
  await safe('auto.plugins', () => put('auto.plugins', navigator.plugins.length === 5 && navigator.mimeTypes.length === 2, navigator.plugins.length + '/' + navigator.mimeTypes.length));
  await safe('auto.notifPerm', async () => {
    const q = await navigator.permissions.query({ name: 'notifications' });
    put('auto.notifPerm', !(Notification.permission === 'denied' && q.state === 'prompt'), Notification.permission + '/' + q.state);
  });
  await safe('auto.outer', () => put('auto.outer', window.outerWidth > 0 && window.outerHeight > 0 && window.outerHeight >= window.innerHeight, `${window.outerWidth}x${window.outerHeight} inner ${window.innerWidth}x${window.innerHeight}`));
  await safe('auto.languages', () => put('auto.languages', navigator.languages[0] === navigator.language && Object.isFrozen(navigator.languages), JSON.stringify(navigator.languages)));
  await safe('auto.cdpRuntimeEnable', () => {
    // Classic Runtime.enable side-channel: console.debug(Error) serializes .stack when Runtime is enabled
    let hit = false;
    const e = new Error();
    Object.defineProperty(e, 'stack', { get() { hit = true; return ''; } });
    console.debug(e);
    put('auto.cdpRuntimeEnable', !hit, hit ? 'Runtime.enable detected' : 'clean');
  });

  // ---------- C. coherence (main thread) ----------
  const main = {};
  main.ua = navigator.userAgent;
  main.platform = navigator.platform;
  main.cores = navigator.hardwareConcurrency;
  main.mem = navigator.deviceMemory;
  main.langs = JSON.stringify(navigator.languages);
  main.tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  main.tzOffset = new Date(2025, 0, 15, 12).getTimezoneOffset();
  main.locale = Intl.DateTimeFormat().resolvedOptions().locale;
  main.scr = `${screen.width}x${screen.height}@${devicePixelRatio} avail ${screen.availWidth}x${screen.availHeight} depth ${screen.colorDepth}/${screen.pixelDepth}`;
  if (navigator.userAgentData) {
    const hv = await navigator.userAgentData.getHighEntropyValues(['platform', 'platformVersion', 'architecture', 'bitness', 'model', 'uaFullVersion', 'fullVersionList', 'wow64', 'formFactors']).catch(e => ({ err: String(e) }));
    main.uad = { brands: navigator.userAgentData.brands, mobile: navigator.userAgentData.mobile, platform: navigator.userAgentData.platform, hv };
  }
  function webglInfo(ctx) {
    if (!ctx) return null;
    const ext = ctx.getExtension('WEBGL_debug_renderer_info');
    return {
      vendor: ext ? ctx.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null,
      renderer: ext ? ctx.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null,
      v: ctx.getParameter(ctx.VERSION), sl: ctx.getParameter(ctx.SHADING_LANGUAGE_VERSION),
      maxTex: ctx.getParameter(ctx.MAX_TEXTURE_SIZE), nExt: (ctx.getSupportedExtensions() || []).length,
    };
  }
  main.webgl = webglInfo(document.createElement('canvas').getContext('webgl'));
  main.webgl2 = webglInfo(document.createElement('canvas').getContext('webgl2'));
  try {
    if (navigator.gpu) { const a = await navigator.gpu.requestAdapter(); main.gpu = a ? a.info.vendor + '/' + a.info.architecture : 'none'; }
    else main.gpu = 'no navigator.gpu';
  } catch (e) { main.gpu = 'err'; }
  try { main.conn = navigator.connection ? navigator.connection.effectiveType + '/' + navigator.connection.rtt + '/' + navigator.connection.downlink : 'none'; } catch (e) { main.conn = 'err'; }
  try { main.quota = navigator.storage ? (await navigator.storage.estimate()).quota : 'none'; } catch (e) { main.quota = 'err'; }
  R._main = main;

  // ---------- B. cross-context consistency ----------
  const workerSrc = `
    (async () => {
      const o = { ua: navigator.userAgent, platform: navigator.platform, cores: navigator.hardwareConcurrency, mem: navigator.deviceMemory,
        langs: JSON.stringify(navigator.languages), tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        tzOffset: new Date(2025, 0, 15, 12).getTimezoneOffset(), locale: Intl.DateTimeFormat().resolvedOptions().locale,
        wd: navigator.webdriver };
      if (navigator.userAgentData) { o.uadPlatform = navigator.userAgentData.platform; o.uadBrands = JSON.stringify(navigator.userAgentData.brands); }
      try { const c = new OffscreenCanvas(4, 4).getContext('webgl'); const e = c.getExtension('WEBGL_debug_renderer_info');
        o.glVendor = c.getParameter(e.UNMASKED_VENDOR_WEBGL); o.glRenderer = c.getParameter(e.UNMASKED_RENDERER_WEBGL); } catch (e) { o.glErr = String(e); }
      postMessage(o);
    })();`;
  const wres = await new Promise((resolve) => {
    try {
      const w = new Worker(URL.createObjectURL(new Blob([workerSrc], { type: 'text/javascript' })));
      w.onmessage = (m) => resolve(m.data);
      w.onerror = (e) => resolve({ error: String(e.message || e) });
      setTimeout(() => resolve({ error: 'timeout' }), 5000);
    } catch (e) { resolve({ error: String(e) }); }
  });
  R._worker = wres;
  const cmp = (id, a, b) => put(id, JSON.stringify(a) === JSON.stringify(b), JSON.stringify({ main: a, worker: b }));
  if (!wres.error) {
    cmp('worker.ua', main.ua, wres.ua);
    cmp('worker.platform', main.platform, wres.platform);
    cmp('worker.cores', main.cores, wres.cores);
    cmp('worker.mem', main.mem, wres.mem);
    cmp('worker.langs', main.langs, wres.langs);
    cmp('worker.tz', main.tz, wres.tz);
    cmp('worker.tzOffset', main.tzOffset, wres.tzOffset);
    cmp('worker.locale', main.locale, wres.locale);
    if (main.uad) cmp('worker.uadPlatform', main.uad.platform, wres.uadPlatform);
    if (main.webgl) cmp('worker.glRenderer', main.webgl.renderer, wres.glRenderer);
    if (main.webgl) cmp('worker.glVendor', main.webgl.vendor, wres.glVendor);
    put('worker.webdriver', wres.wd === undefined || wres.wd === false, String(wres.wd));
  } else put('worker.run', false, wres.error);

  // iframe consistency (srcdoc + about:blank created at runtime)
  for (const mode of ['blank', 'srcdoc']) {
    await safe('iframe.' + mode, async () => {
      const f = document.createElement('iframe');
      f.style.display = 'none';
      if (mode === 'srcdoc') f.srcdoc = '<html></html>';
      document.body.appendChild(f);
      await new Promise(r => setTimeout(r, 100));
      const w = f.contentWindow;
      const o = { ua: w.navigator.userAgent, platform: w.navigator.platform, cores: w.navigator.hardwareConcurrency, langs: JSON.stringify(w.navigator.languages),
        tz: w.Intl.DateTimeFormat().resolvedOptions().timeZone, wd: w.navigator.webdriver };
      let gl = null;
      try { const c = w.document.createElement('canvas').getContext('webgl'); const e = c.getExtension('WEBGL_debug_renderer_info'); gl = c.getParameter(e.UNMASKED_RENDERER_WEBGL); } catch (e) { gl = 'ERR ' + e; }
      const ok = o.ua === main.ua && o.platform === main.platform && o.cores === main.cores && o.langs === main.langs && o.tz === main.tz && o.wd === false && (!main.webgl || gl === main.webgl.renderer);
      put('iframe.' + mode, ok, JSON.stringify({ o, gl }));
      f.remove();
    });
  }

  // ---------- coherence rules ----------
  const ua = main.ua;
  const osFromUa = /Windows NT/.test(ua) ? 'windows' : /Macintosh/.test(ua) ? 'macos' : /Linux/.test(ua) ? 'linux' : '?';
  const osFromPlat = /^Win/.test(main.platform) ? 'windows' : /^Mac/.test(main.platform) ? 'macos' : /Linux/.test(main.platform) ? 'linux' : '?';
  const osFromUad = main.uad ? ({ 'Windows': 'windows', 'macOS': 'macos', 'Linux': 'linux' }[main.uad.platform] || '?') : null;
  const glr = (main.webgl && main.webgl.renderer) || '';
  const osFromGl = /Direct3D|D3D11/.test(glr) ? 'windows' : /Apple|Metal/.test(glr) ? 'macos' : /Mesa|llvmpipe|OpenGL/.test(glr) ? 'linux' : '?';
  put('coh.os', osFromUa === osFromPlat && (osFromUad === null || osFromUad === osFromUa) && (osFromGl === '?' || osFromGl === osFromUa || (osFromUa === 'macos' && osFromGl === 'macos')),
    JSON.stringify({ ua: osFromUa, platform: osFromPlat, uad: osFromUad, gl: osFromGl }));
  if (main.uad) {
    const m = ua.match(/Chrome\/(\d+)/);
    const brandVer = (main.uad.brands.find(b => b.brand === 'Google Chrome' || b.brand === 'Microsoft Edge') || {}).version;
    put('coh.version', m && brandVer === m[1], JSON.stringify({ ua: m && m[1], brand: brandVer }));
    const full = (main.uad.hv && main.uad.hv.uaFullVersion) || '';
    put('coh.fullVersion', full.startsWith(m ? m[1] + '.' : '?'), full);
    const hvPlatform = main.uad.hv && main.uad.hv.platform;
    put('coh.hvPlatform', hvPlatform === main.uad.platform, hvPlatform + ' vs ' + main.uad.platform);
  }
  put('coh.tzOffset', (() => { try { const f = new Intl.DateTimeFormat('en-US', { timeZone: main.tz, timeZoneName: 'shortOffset' }).formatToParts(new Date(2025, 0, 15, 12)).find(p => p.type === 'timeZoneName').value;
    const m = f.match(/GMT([+-]\d+)?(?::(\d+))?/); const mins = m && m[1] ? (parseInt(m[1]) * 60 + Math.sign(parseInt(m[1])) * parseInt(m[2] || 0)) : 0; return -mins === main.tzOffset; } catch (e) { return false; } })(), main.tz + ' offset ' + main.tzOffset);
  put('coh.screen', screen.availWidth <= screen.width && screen.availHeight <= screen.height && screen.width >= screen.height * 1.2 - 1, main.scr);


  // ---------- F. other realms: cross-origin iframe, popup, SW, shared worker ----------
  const probeSrc = (typeof window !== 'undefined' ? null : null);
  const wantKeys = ['ua', 'platform', 'cores', 'mem', 'langs', 'tz', 'locale', 'uadPlatform', 'glRenderer', 'glVendor', 'gpu', 'conn', 'quota'];
  const wantMain = { ua: main.ua, platform: main.platform, cores: main.cores, mem: main.mem, langs: main.langs, tz: main.tz, locale: main.locale,
    uadPlatform: main.uad && main.uad.platform, glRenderer: main.webgl && main.webgl.renderer, glVendor: main.webgl && main.webgl.vendor, gpu: main.gpu, conn: main.conn, quota: main.quota };
  const diff = (o) => wantKeys.filter(k => JSON.stringify(o[k]) !== JSON.stringify(wantMain[k])).map(k => k + ': ' + JSON.stringify(wantMain[k]) + ' != ' + JSON.stringify(o[k]));
  const expectMsg = (pred, ms) => new Promise(res => { const t = setTimeout(() => { removeEventListener('message', h); res(null); }, ms);
    const h = (e) => { if (e.data && e.data.probe && pred(e)) { clearTimeout(t); removeEventListener('message', h); res(e.data.probe); } }; addEventListener('message', h); });
  const origin2 = location.protocol + '//localhost:' + location.port; // different site -> out-of-process iframe
  await safe('realm.xorigin_iframe', async () => {
    const f = document.createElement('iframe'); f.src = origin2 + '/frame'; f.style.display = 'none';
    const p = expectMsg(e => e.source === f.contentWindow, 8000); document.body.appendChild(f); const o = await p;
    if (!o) { put('realm.xorigin_iframe', false, 'no reply'); return; }
    const d = diff(o);
    const scr = o.screen && main.scr ? JSON.stringify(o.screen) : '';
    put('realm.xorigin_iframe', d.length === 0, d.join(' | ') + ' screen=' + scr);
  });
  await safe('realm.popup', async () => {
    const p = expectMsg(e => true, 8000); const w = window.open(location.origin + '/frame', '_blank', 'popup,width=300,height=200'); const o = await p;
    try { w && w.close(); } catch (e) {}
    if (!o) { put('realm.popup', false, 'no reply (popup blocked?)'); return; }
    const d = diff(o); put('realm.popup', d.length === 0, d.join(' | '));
  });
  await safe('realm.sharedworker', async () => {
    const w = new SharedWorker('/shared.js'); const o = await new Promise(res => { const t = setTimeout(() => res(null), 8000); w.port.onmessage = e => { clearTimeout(t); res(e.data.probe); }; w.port.start(); });
    if (!o) { put('realm.sharedworker', false, 'no reply'); return; }
    const d = diff(o); put('realm.sharedworker', d.length === 0, d.join(' | '));
  });
  await safe('realm.serviceworker', async () => {
    const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    await navigator.serviceWorker.ready;
    const sw = reg.active || reg.waiting || reg.installing;
    const p = new Promise(res => { const t = setTimeout(() => res(null), 8000); navigator.serviceWorker.addEventListener('message', e => { clearTimeout(t); res(e.data.probe); }); });
    sw.postMessage('probe'); const o = await p;
    await reg.unregister();
    if (!o) { put('realm.serviceworker', false, 'no reply'); return; }
    const d = diff(o); put('realm.serviceworker', d.length === 0, d.join(' | '));
  });
  await safe('desc.noProtoOnWrappers', () => {
    const fns = [Object.getOwnPropertyDescriptor(Navigator.prototype, 'deviceMemory').get, WebGLRenderingContext.prototype.getParameter, Function.prototype.toString,
      HTMLCanvasElement.prototype.toDataURL, CanvasRenderingContext2D.prototype.getImageData];
    const bad = fns.filter(f => f.hasOwnProperty('prototype') || (() => { try { new f(); return true; } catch (e) { return false; } })());
    put('desc.noProtoOnWrappers', bad.length === 0, bad.map(f => f.name).join(','));
  });
  await safe('desc.keysOrder', () => {
    const keys = Reflect.ownKeys(Navigator.prototype).map(String).join(',');
    put('desc.keysOrder', true, keys.length);
  });
  await safe('auto.mq', () => {
    put('auto.mq', matchMedia('(device-width: ' + screen.width + 'px)').matches && matchMedia('(device-height: ' + screen.height + 'px)').matches &&
      matchMedia('(resolution: ' + devicePixelRatio + 'dppx)').matches, `dw ${screen.width} dpr ${devicePixelRatio}`);
  });

  // ---------- G. host leaks that used to show through: colour, battery, WebGPU ----------
  const gettersAreNative = (proto, keys) => keys.every(k => {
    const g = Object.getOwnPropertyDescriptor(proto, k).get;
    const ts = Function.prototype.toString.call(g);
    let illegal = false;
    try { g.call({}); } catch (e) { illegal = e instanceof TypeError; }
    return NATIVE.test(ts) && g.name === 'get ' + k && !g.hasOwnProperty('prototype') && illegal;
  });
  await safe('host.colorDepth', () => {
    const wide = matchMedia('(color-gamut: p3)').matches;
    const ok = (screen.colorDepth === 30) === wide && screen.pixelDepth === screen.colorDepth && (screen.colorDepth === 24 || screen.colorDepth === 30);
    put('host.colorDepth', ok && gettersAreNative(Screen.prototype, ['colorDepth', 'pixelDepth']), `depth ${screen.colorDepth}/${screen.pixelDepth} p3 ${wide}`);
  });
  await safe('host.dynamicRange', () => {
    put('host.dynamicRange', !matchMedia('(dynamic-range: high)').matches && !matchMedia('(video-dynamic-range: high)').matches, 'an HDR panel must not show through');
  });
  await safe('host.battery', async () => {
    const b = await navigator.getBattery();
    const ok = b.charging === true && b.level === 1 && b.chargingTime === 0 && b.dischargingTime === Infinity && b instanceof BatteryManager;
    put('host.battery', ok && gettersAreNative(BatteryManager.prototype, ['charging', 'level', 'chargingTime', 'dischargingTime']),
      JSON.stringify({ c: b.charging, l: b.level, ct: b.chargingTime, dt: String(b.dischargingTime) }));
  });
  await safe('host.webgpu', async () => {
    if (!navigator.gpu) { put('host.webgpu', true, 'no navigator.gpu'); return; }
    const a = await navigator.gpu.requestAdapter();
    if (!a) { put('host.webgpu', true, 'no adapter'); return; }
    const vendor = a.info.vendor;
    const gl = String(main.webgl && main.webgl.renderer || '').toLowerCase();
    const same = vendor === 'apple' ? /apple|metal/.test(gl) : gl.indexOf(vendor) !== -1;
    put('host.webgpu', same && a.info.architecture !== '' && gettersAreNative(GPUAdapterInfo.prototype, ['vendor', 'architecture']),
      `${vendor}/${a.info.architecture} vs webgl "${gl.slice(0, 60)}"`);
  });

  // ---------- E. canvas / audio fingerprints (informational) ----------
  await safe('fp.canvas', () => {
    const c = document.createElement('canvas'); c.width = 200; c.height = 50;
    const x = c.getContext('2d'); x.textBaseline = 'top'; x.font = '14px Arial'; x.fillStyle = '#f60'; x.fillRect(125, 1, 62, 20);
    x.fillStyle = '#069'; x.fillText('Cwm fjordbank glyphs vext quiz, \u{1F603}', 2, 15);
    const a = c.toDataURL(), b = c.toDataURL();
    let h = 0; for (let i = 0; i < a.length; i++) h = (h * 31 + a.charCodeAt(i)) | 0;
    put('fp.canvas', a === b, 'hash ' + h + ' stable=' + (a === b));
  });
  await safe('fp.fonts', () => {
    const probe = ['Segoe UI', 'Calibri', 'Cambria', 'Consolas', 'Tahoma', 'Helvetica Neue', 'Menlo', 'SF Pro Text', 'Apple Color Emoji', 'Ubuntu', 'DejaVu Sans', 'Arial', 'Times New Roman'];
    const span = document.createElement('span'); span.style.cssText = 'position:absolute;left:-9999px;font-size:72px'; span.textContent = 'mmmmmmmmmmlli';
    document.body.appendChild(span);
    const base = {}; for (const b of ['monospace', 'serif', 'sans-serif']) { span.style.fontFamily = b; base[b] = span.offsetWidth; }
    const present = probe.filter(f => ['monospace', 'serif', 'sans-serif'].some(b => { span.style.fontFamily = `'${f}',${b}`; return span.offsetWidth !== base[b]; }));
    span.remove();
    R._fonts = present;
    put('fp.fonts', true, present.join(','));
  });
  R._plugins = Array.from(navigator.plugins).map(p => p.name);
  R._connection = navigator.connection ? { rtt: navigator.connection.rtt, dl: navigator.connection.downlink, et: navigator.connection.effectiveType } : null;
  R._voices = (speechSynthesis.getVoices() || []).length;
  return JSON.stringify(R);
})()
