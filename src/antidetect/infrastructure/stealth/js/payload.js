/* Renderer-side fingerprint layer.
 *
 * Injected by the CDP target manager *before* any page script runs (main
 * frames, same-process iframes and — via a Runtime.evaluate prelude — dedicated,
 * shared and service workers).
 *
 * Design rules (each one exists because a public detector checks for it):
 *   1. Native first. Everything Chrome can emulate itself (UA, UA-CH, platform,
 *      locale, timezone, hardwareConcurrency, screen size) is done over CDP in
 *      C++ and never touched here. This file only patches what CDP cannot.
 *   2. Patch only on difference. A property that already equals the wanted
 *      value is left alone, so a profile that matches the host patches nothing.
 *   3. Prototype level, descriptor-perfect. Getters/methods are replaced on the
 *      prototype that owns them using object-literal accessors/methods, so name,
 *      length, descriptor shape, absence of `prototype` and non-constructibility
 *      match the native ones, and a bad receiver still throws the native
 *      "Illegal invocation" (the original function is what validates `this`).
 *   4. Function.prototype.toString answers `[native code]` for everything this
 *      file defines. Its answers are shared between realms (iframes): every
 *      wrapper is registered with the top accessible window, and a realm that
 *      is asked about a function it does not know consults that registry over a
 *      secret handshake — so a detector that stringifies our functions through
 *      a *sibling* iframe's toString still sees native code.
 *   5. Error stacks are scrubbed of our frames; no globals, no leftovers.
 */
(function (CFG) {
  'use strict';

  var G = typeof globalThis !== 'undefined' ? globalThis : self;
  var IS_WORKER = typeof WorkerGlobalScope !== 'undefined' && G instanceof WorkerGlobalScope;

  // Privileged / internal documents must stay untouched. (Never read
  // `location` in a worker: before its script is fetched the getter blocks
  // the very Runtime.evaluate that is running this prelude.)
  if (!IS_WORKER) {
    try {
      var proto0 = G.location && G.location.protocol;
      if (/^(chrome|chrome-untrusted|chrome-extension|chrome-search|devtools|chrome-error):$/.test(proto0)) return;
    } catch (e0) { /* no location: continue */ }
  }

  // ---------------------------------------------------------------- toolkit
  var _defProp = Object.defineProperty;
  var _gopd = Object.getOwnPropertyDescriptor;
  var _apply = Reflect.apply;
  var _WeakMap = WeakMap;
  var _WeakSet = WeakSet;
  var _freeze = Object.freeze;
  var _nativeToString = Function.prototype.toString;
  var TOKEN = CFG.token;

  function scrub(err) {
    try {
      if (err && typeof err === 'object' && typeof err.stack === 'string') {
        var lines = err.stack.split('\n');
        var kept = [];
        for (var i = 0; i < lines.length; i++) if (lines[i].indexOf(TOKEN) === -1) kept.push(lines[i]);
        err.stack = kept.join('\n');
      }
    } catch (e1) { /* frozen error: ignore */ }
    return err;
  }

  // Highest same-origin ancestor window: where all realms share one registry.
  var ROOT_TO_STRING = null;
  if (!IS_WORKER) {
    try {
      var up = G;
      while (up.parent && up.parent !== up) {
        var next = up.parent;
        void next.Function; // throws for a cross-origin parent
        up = next;
      }
      if (up !== G) ROOT_TO_STRING = up.Function.prototype.toString;
    } catch (e2) { /* cross-origin ancestor: this realm stands alone */ }
  }

  var NATIVE_SRC = new _WeakMap();

  // Method shorthand: no own `prototype`, not constructible — like the real one.
  var fakeToString = ({
    toString() {
      try {
        if (arguments.length >= 2 && arguments[0] === TOKEN) {
          // Secret handshake from another realm of this page (never reachable
          // by page code: the token only exists in this closure).
          if (arguments[1] === 'get') return NATIVE_SRC.get(this);
          if (arguments[1] === 'set') { NATIVE_SRC.set(this, arguments[2]); return undefined; }
        }
        var known = NATIVE_SRC.get(this);
        if (known !== undefined) return known;
        if (ROOT_TO_STRING !== null) {
          var shared = _apply(ROOT_TO_STRING, this, [TOKEN, 'get']);
          if (typeof shared === 'string') return shared;
        }
        return _apply(_nativeToString, this, []);
      } catch (err) { throw scrub(err); }
    }
  }).toString;

  function register(fn, src) {
    NATIVE_SRC.set(fn, src);
    if (ROOT_TO_STRING !== null) {
      try { _apply(ROOT_TO_STRING, fn, [TOKEN, 'set', src]); } catch (e3) { /* root replaced: ignore */ }
    }
  }
  try {
    _defProp(Function.prototype, 'toString', { value: fakeToString, writable: true, configurable: true, enumerable: false });
    register(fakeToString, 'function toString() { [native code] }');
  } catch (e4) { /* ignore */ }

  function ownDesc(obj, key) { try { return _gopd(obj, key); } catch (e) { return undefined; } }

  // Replace a native accessor getter on `holder`, keeping the descriptor shape.
  function patchGetter(holder, key, valueFn) {
    if (!holder) return false;
    var d = ownDesc(holder, key);
    if (!d || typeof d.get !== 'function') return false;
    var origGet = d.get;
    var getter = _gopd({
      get [key]() {
        try {
          var native = _apply(origGet, this, []); // throws "Illegal invocation" natively
          return valueFn.call(this, native);
        } catch (err) { throw scrub(err); }
      }
    }, key).get;
    register(getter, 'function get ' + key + '() { [native code] }');
    _defProp(holder, key, { get: getter, set: d.set, enumerable: d.enumerable, configurable: d.configurable });
    return true;
  }

  // Replace a native method, keeping name/length/attributes.
  function patchMethod(holder, key, makeImpl) {
    if (!holder) return false;
    var d = ownDesc(holder, key);
    if (!d || typeof d.value !== 'function') return false;
    var orig = d.value;
    var impl = makeImpl(orig);
    var method = ({
      [key]() {
        try { return _apply(impl, this, arguments); } catch (err) { throw scrub(err); }
      }
    })[key];
    _defProp(method, 'length', { value: orig.length, configurable: true });
    register(method, 'function ' + key + '() { [native code] }');
    _defProp(holder, key, { value: method, writable: d.writable, enumerable: d.enumerable, configurable: d.configurable });
    return true;
  }

  // ------------------------------------------------------- deterministic PRNG
  var SEED = CFG.seed >>> 0;
  function mix(a, b) {
    var h = (a ^ Math.imul(b | 0, 0x9E3779B1)) >>> 0;
    h = Math.imul(h ^ (h >>> 15), 0x85EBCA77) >>> 0;
    h = Math.imul(h ^ (h >>> 13), 0xC2B2AE3D) >>> 0;
    return (h ^ (h >>> 16)) >>> 0;
  }

  // ------------------------------------------------------------- navigator
  var navProtos = [];
  if (typeof Navigator !== 'undefined') navProtos.push(Navigator.prototype);
  if (typeof WorkerNavigator !== 'undefined') navProtos.push(WorkerNavigator.prototype);

  function nav(key, wanted, force) {
    if (wanted === undefined || wanted === null) return;
    for (var i = 0; i < navProtos.length; i++) {
      var d = ownDesc(navProtos[i], key);
      if (!d || typeof d.get !== 'function') continue;
      var current;
      try { current = _apply(d.get, G.navigator, []); } catch (e) { continue; }
      if (!force && current === wanted) return; // patch only on difference
      patchGetter(navProtos[i], key, function () { return wanted; });
    }
  }

  // Window main frames get these natively from Emulation.*; workers do not.
  if (IS_WORKER) {
    nav('platform', CFG.platform);
    nav('hardwareConcurrency', CFG.cores);
    nav('userAgent', CFG.userAgent);
    if (CFG.appVersion) nav('appVersion', CFG.appVersion);
  }
  // Window frames get `platform` natively too, but Chrome drops exactly that one
  // override when a tab changes renderer process (New Tab page -> a website), so the
  // page would see the real OS. Patch only when it still differs (rule 2): everywhere
  // the CDP override held, this changes nothing.
  if (!IS_WORKER) nav('platform', CFG.platform);
  // deviceMemory has no CDP override at all.
  (function () {
    if (!CFG.deviceMemory) return;
    nav('deviceMemory', CFG.deviceMemory);
  })();
  // languages: native in practice (--accept-lang); only patch a real mismatch.
  (function () {
    if (!CFG.languages || !CFG.languages.length) return;
    var cur;
    try { cur = G.navigator.languages; } catch (e) { return; }
    var same = cur && cur.length === CFG.languages.length;
    for (var i = 0; same && i < cur.length; i++) if (cur[i] !== CFG.languages[i]) same = false;
    if (same) return;
    var frozen = _freeze(CFG.languages.slice());
    for (var j = 0; j < navProtos.length; j++) {
      patchGetter(navProtos[j], 'languages', function () { return frozen; });
      patchGetter(navProtos[j], 'language', function () { return frozen[0]; });
    }
  })();

  // ---------------------------------------------------------- speech voices
  // speechSynthesis.getVoices() answers from the host: a Windows profile on a Mac would list
  // Zarvox and Trinoids, and the default voice would speak the host's language while Intl
  // says German. Window frames list the voices a real Chrome of the claimed OS and language
  // has instead. They are objects of the real SpeechSynthesisVoice prototype; its accessors
  // answer for them and still defer to the native getter for every genuine voice.
  (function () {
    var V = CFG.voices;
    if (IS_WORKER || !V || !V.length) return;
    if (typeof SpeechSynthesis === 'undefined' || typeof SpeechSynthesisVoice === 'undefined') return;
    var VP = SpeechSynthesisVoice.prototype;
    var records = new _WeakMap();
    var voices = [];
    for (var i = 0; i < V.length; i++) {
      var voice = Object.create(VP);
      records.set(voice, V[i]);
      voices.push(voice);
    }

    function patchOwnGetter(holder, key, pick) {
      var d = ownDesc(holder, key);
      if (!d || typeof d.get !== 'function') return;
      var origGet = d.get;
      var getter = _gopd({
        get [key]() {
          try {
            var rec = records.get(this);
            return rec !== undefined ? pick(rec) : _apply(origGet, this, []);
          } catch (err) { throw scrub(err); }
        }
      }, key).get;
      register(getter, 'function get ' + key + '() { [native code] }');
      _defProp(holder, key, { get: getter, set: d.set, enumerable: d.enumerable, configurable: d.configurable });
    }
    patchOwnGetter(VP, 'name', function (r) { return r.n; });
    patchOwnGetter(VP, 'voiceURI', function (r) { return r.n; });
    patchOwnGetter(VP, 'lang', function (r) { return r.l; });
    patchOwnGetter(VP, 'localService', function (r) { return r.s; });
    patchOwnGetter(VP, 'default', function (r) { return r.d; });

    patchMethod(SpeechSynthesis.prototype, 'getVoices', function (orig) {
      return function getVoices() {
        _apply(orig, this, []); // validates the receiver and keeps the native voice loading / events alive
        return voices.slice();
      };
    });

    // A page may hand one of our voices to an utterance: the native setter only takes real
    // ones, so it gets null (= the system voice) and the getter reports what the page chose.
    if (typeof SpeechSynthesisUtterance !== 'undefined') {
      var UP = SpeechSynthesisUtterance.prototype;
      var ud = ownDesc(UP, 'voice');
      if (ud && typeof ud.get === 'function' && typeof ud.set === 'function') {
        var chosen = new _WeakMap();
        var nativeGet = ud.get, nativeSet = ud.set;
        var voiceGet = _gopd({
          get voice() {
            try {
              var picked = chosen.get(this);
              return picked !== undefined ? picked : _apply(nativeGet, this, []);
            } catch (err) { throw scrub(err); }
          }
        }, 'voice').get;
        var voiceSet = _gopd({
          set voice(v) {
            try {
              if (v !== null && typeof v === 'object' && records.has(v)) {
                _apply(nativeSet, this, [null]);
                chosen.set(this, v);
              } else {
                _apply(nativeSet, this, [v]);
                chosen.delete(this);
              }
            } catch (err) { throw scrub(err); }
          }
        }, 'voice').set;
        register(voiceGet, 'function get voice() { [native code] }');
        register(voiceSet, 'function set voice() { [native code] }');
        _defProp(UP, 'voice', { get: voiceGet, set: voiceSet, enumerable: ud.enumerable, configurable: ud.configurable });
      }
    }
  })();

  // ------------------------------------------------------------ UA client hints
  // Main frames get userAgentData natively from Emulation.setUserAgentOverride.
  // Shared and service workers are not reached by it, so their NavigatorUAData
  // is patched here (only when it differs from what the profile claims).
  (function () {
    var ua = CFG.uaData;
    if (!ua || typeof NavigatorUAData === 'undefined') return;
    var data;
    try { data = G.navigator.userAgentData; } catch (e) { return; }
    if (!data) return;
    var P = NavigatorUAData.prototype;
    var curBrands;
    try { curBrands = JSON.stringify(data.brands); } catch (e) { curBrands = ''; }
    if (data.platform === ua.platform && curBrands === JSON.stringify(ua.brands)) return;
    var brands = _freeze(ua.brands.map(function (b) { return _freeze({ brand: b.brand, version: b.version }); }));
    patchGetter(P, 'brands', function () { return brands; });
    patchGetter(P, 'mobile', function () { return !!ua.mobile; });
    patchGetter(P, 'platform', function () { return ua.platform; });
    var fieldFor = {
      architecture: ua.architecture, bitness: ua.bitness, model: ua.model,
      platformVersion: ua.platformVersion, uaFullVersion: ua.uaFullVersion,
      wow64: !!ua.wow64, formFactors: ua.formFactors, fullVersionList: ua.fullVersionList
    };
    patchMethod(P, 'getHighEntropyValues', function (orig) {
      return function (hints) {
        return _apply(orig, this, arguments).then(function (v) {
          v.brands = brands; v.mobile = !!ua.mobile; v.platform = ua.platform;
          for (var k in fieldFor) if (Object.prototype.hasOwnProperty.call(v, k)) v[k] = fieldFor[k];
          return v;
        });
      };
    });
    patchMethod(P, 'toJSON', function (orig) {
      return function () {
        var o = _apply(orig, this, arguments);
        o.brands = brands; o.mobile = !!ua.mobile; o.platform = ua.platform;
        return o;
      };
    });
  })();

  // ---------------------------------------------------------------- screen
  // Size/DPR come natively from Emulation.setDeviceMetricsOverride; the OS
  // chrome insets (taskbar / menu bar) have no CDP override, so avail* is
  // patched here and only where it differs.
  // colorDepth / pixelDepth: Chrome reads the display's own value (30 on a P3 Mac), which a
  // Windows or Linux profile never reports; --force-color-profile does not touch them.
  if (!IS_WORKER && CFG.screen && typeof Screen !== 'undefined') {
    [['availWidth', 'availWidth'], ['availHeight', 'availHeight'], ['availLeft', 'availLeft'],
     ['availTop', 'availTop'], ['colorDepth', 'colorDepth'], ['pixelDepth', 'colorDepth']].forEach(function (pair) {
      var k = pair[0];
      var wanted = CFG.screen[pair[1]];
      if (wanted === undefined || wanted === null) return;
      var d = ownDesc(Screen.prototype, k);
      if (!d || typeof d.get !== 'function') return;
      var cur;
      try { cur = _apply(d.get, G.screen, []); } catch (e) { return; }
      if (cur === wanted) return;
      patchGetter(Screen.prototype, k, function () { return wanted; });
    });
  }

  // --------------------------------------------------------------- battery
  // The host's real battery (charging flag, level, time left) is the same in every profile
  // and quietly ties them to one machine. A desktop without a battery answers exactly this,
  // which is also what a laptop on the charger shows.
  if (!IS_WORKER && typeof BatteryManager !== 'undefined') {
    patchGetter(BatteryManager.prototype, 'charging', function () { return true; });
    patchGetter(BatteryManager.prototype, 'chargingTime', function () { return 0; });
    patchGetter(BatteryManager.prototype, 'dischargingTime', function () { return Infinity; });
    patchGetter(BatteryManager.prototype, 'level', function () { return 1; });
  }

  // ---------------------------------------------------------------- webgpu
  // navigator.gpu names the adapter independently of WebGL: left alone, a profile that claims an
  // NVIDIA card in WebGL answers "apple / metal-3" here. Window and worker contexts both.
  (function () {
    var gpu = CFG.webgl && CFG.webgl.gpu;
    if (!gpu) return;
    var patched = false;
    function patchInfo(proto) {
      if (patched || !proto) return;
      patched = true;
      if (gpu.vendor) patchGetter(proto, 'vendor', function () { return gpu.vendor; });
      if (gpu.architecture) patchGetter(proto, 'architecture', function () { return gpu.architecture; });
    }
    if (typeof GPUAdapterInfo !== 'undefined') { patchInfo(GPUAdapterInfo.prototype); return; }
    // Workers install WebGPU's interfaces lazily (measured: GPUAdapterInfo is still undefined
    // while this runs in shared and service workers, yet navigator.gpu already answers), so the
    // class is reached through the first adapter instead.
    var entry;
    try { entry = G.navigator && G.navigator.gpu; } catch (e5) { return; }
    if (!entry) return;
    patchMethod(Object.getPrototypeOf(entry), 'requestAdapter', function (orig) {
      return function requestAdapter() {
        return _apply(orig, this, arguments).then(function (adapter) {
          try { if (adapter) patchInfo(Object.getPrototypeOf(adapter.info)); } catch (e6) { /* no info: leave it */ }
          return adapter;
        });
      };
    });
  })();

  // ----------------------------------------------- connection and storage
  // navigator.connection (round-trip time, bandwidth) and the storage quota come from the host's
  // network and disk: the same numbers in every profile on one computer. Each profile reports its
  // own.
  //
  // `navigator.connection` must NOT be read in a worker while it is paused at start: that read
  // blocks (measured: every Worker / SharedWorker / ServiceWorker the page created hung its main
  // thread, and the Runtime.evaluate with it), the same trap as `self.location`. The class is
  // patched by name instead. `navigator.storage` answers fine there, so its class is found from
  // the object, as WebGPU's is in the section above.
  (function () {
    var conn = CFG.connection;
    if (conn) {
      var NP = null;
      if (typeof NetworkInformation !== 'undefined') NP = NetworkInformation.prototype;
      else if (!IS_WORKER) {
        try { NP = Object.getPrototypeOf(G.navigator.connection); } catch (e7) { NP = null; }
      }
      if (NP) {
        patchGetter(NP, 'effectiveType', function () { return conn.effectiveType; });
        patchGetter(NP, 'rtt', function () { return conn.rtt; });
        patchGetter(NP, 'downlink', function () { return conn.downlink; });
      }
    }
    var quota = CFG.storageQuota;
    var store;
    try { store = G.navigator && G.navigator.storage; } catch (e8) { store = null; }
    if (quota && store) {
      patchMethod(Object.getPrototypeOf(store), 'estimate', function (orig) {
        return function estimate() {
          return _apply(orig, this, arguments).then(function (est) {
            if (est && typeof est === 'object' && typeof est.quota === 'number') {
              est.quota = Math.max(quota, est.usage || 0);
            }
            return est;
          });
        };
      });
    }
  })();

  // ----------------------------------------------------------------- webgl
  function patchWebGL(Ctor, which) {
    if (!Ctor || !Ctor.prototype || !CFG.webgl) return;
    var cfg = CFG.webgl;
    var P = Ctor.prototype;
    patchMethod(P, 'getParameter', function (orig) {
      return function (pname) {
        var v = _apply(orig, this, arguments);
        if (v === null || v === undefined) return v;
        if (pname === 0x9245 && cfg.vendor) return cfg.vendor;
        if (pname === 0x9246 && cfg.renderer) return cfg.renderer;
        var table = cfg.params && cfg.params[which];
        if (table) {
          var spec = table[pname];
          if (spec !== undefined) {
            if (spec && typeof spec === 'object') {
              if (spec.f32) return new Float32Array(spec.f32);
              if (spec.i32) return new Int32Array(spec.i32);
            }
            return spec;
          }
        }
        return v;
      };
    });
    var allowed = cfg.extensions && cfg.extensions[which];
    if (allowed) {
      var allowSet = {};
      for (var i = 0; i < allowed.length; i++) allowSet[allowed[i]] = true;
      patchMethod(P, 'getSupportedExtensions', function (orig) {
        return function () {
          var list = _apply(orig, this, arguments);
          if (!list) return list;
          var out = [];
          for (var j = 0; j < list.length; j++) if (allowSet[list[j]]) out.push(list[j]);
          return out;
        };
      });
      patchMethod(P, 'getExtension', function (orig) {
        return function (name) {
          var ext = _apply(orig, this, arguments);
          if (ext && typeof name === 'string' && !allowSet[name]) return null;
          return ext;
        };
      });
    }
    if (cfg.noise !== false) {
      patchMethod(P, 'readPixels', function (orig) {
        return function () {
          var r = _apply(orig, this, arguments);
          try {
            var buf = arguments[6];
            if (arguments[4] === 0x1908 && arguments[5] === 0x1401 && buf && buf.length &&
                (buf instanceof Uint8Array || buf instanceof Uint8ClampedArray)) {
              var x0 = arguments[0] | 0, y0 = arguments[1] | 0, w = arguments[2] | 0;
              noiseRGBA(buf, w, x0, y0, 0x57474C);
            }
          } catch (e) { /* ignore */ }
          return r;
        };
      });
    }
  }
  patchWebGL(typeof WebGLRenderingContext !== 'undefined' ? WebGLRenderingContext : null, 'webgl');
  patchWebGL(typeof WebGL2RenderingContext !== 'undefined' ? WebGL2RenderingContext : null, 'webgl2');

  // ------------------------------------------------------------------ fonts
  // Cross-OS profiles only. A font family declared through @font-face shadows
  // the system font of the same name, which lets us (a) hide fonts the claimed
  // OS does not have and (b) make fonts it does have look installed:
  //   hide: valid face, but restricted to U+10FFFF -> every real character falls
  //         through to the next family, exactly as if the font were absent;
  //   fake: face backed by a stand-in system font whose metrics differ from the
  //         generic fallbacks, so width probes see "installed".
  if (!IS_WORKER && CFG.fonts && typeof CSSStyleSheet !== 'undefined' && G.document) {
    try {
      var probe = (typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(8, 8) : G.document.createElement('canvas')).getContext('2d');
      var textProbe = 'mmmmmmmmmmlliWW';
      var width = function (family) { probe.font = '72px ' + family; return probe.measureText(textProbe).width; };
      var bases = ['monospace', 'sans-serif', 'serif'].map(function (b) { return [b, width(b)]; });
      var hostHas = function (name) {
        for (var i = 0; i < bases.length; i++) if (width('"' + name + '",' + bases[i][0]) !== bases[i][1]) return true;
        return false;
      };
      var q = function (s) { return '"' + String(s).replace(/["\\]/g, '') + '"'; };
      var rules = [];
      CFG.fonts.hide.forEach(function (name) {
        rules.push('@font-face{font-family:' + q(name) + ';src:local("Arial"),local("Helvetica"),local("DejaVu Sans");unicode-range:U+10FFFF;}');
      });
      // Stand-ins must be *clearly* wider/narrower than every generic fallback
      // (probes often round offsetWidth), so they are chosen on this host.
      var candidates = ['Verdana', 'Trebuchet MS', 'Georgia', 'Comic Sans MS', 'Impact', 'Palatino', 'Palatino Linotype', 'Tahoma'];
      var usable = candidates.filter(function (name) {
        for (var i = 0; i < bases.length; i++) {
          var w = width('"' + name + '",' + bases[i][0]);
          if (Math.abs(w - bases[i][1]) < bases[i][1] * 0.02) return false;
        }
        return true;
      });
      CFG.fonts.fake.forEach(function (pair, idx) {
        if (!usable.length || hostHas(pair[0])) return; // host really has it (e.g. Office fonts): keep it
        rules.push('@font-face{font-family:' + q(pair[0]) + ';src:local(' + q(usable[idx % usable.length]) + ');}');
      });
      if (rules.length) {
        var sheet = new CSSStyleSheet();
        sheet.replaceSync(rules.join('\n'));
        G.document.adoptedStyleSheets = G.document.adoptedStyleSheets.concat([sheet]);
      }
    } catch (eF) { /* fonts stay native */ }
  }

  // ------------------------------------------------------------ canvas noise
  // Deterministic, per-profile, sparse +/-1 on edge pixels only: solid fills
  // stay exact (a classic noise detector), repeated reads agree (stable fp).
  function noiseRGBA(data, width, ox, oy, salt) {
    if (!data || !width) return;
    var len = data.length;
    var stride = width * 4;
    for (var i = 0; i < len; i += 4) {
      if (data[i + 3] === 0) continue;
      var px = (i % stride) >> 2, py = (i / stride) | 0;
      var h = mix(mix(SEED ^ salt, ox + px), oy + py);
      if ((h & 31) !== 0) continue; // ~3% of pixels
      // edge test against left / upper neighbour: skip flat regions
      var left = px > 0 ? i - 4 : -1, up = py > 0 ? i - stride : -1;
      var edge = (left >= 0 && (data[left] !== data[i] || data[left + 1] !== data[i + 1] || data[left + 2] !== data[i + 2])) ||
                 (up >= 0 && (data[up] !== data[i] || data[up + 1] !== data[i + 1] || data[up + 2] !== data[i + 2]));
      if (!edge) continue;
      var ch = (h >>> 5) % 3;
      var delta = (h & 0x20) ? 1 : -1;
      var v = data[i + ch] + delta;
      data[i + ch] = v < 0 ? 0 : v > 255 ? 255 : v;
    }
  }

  if (CFG.noise && CFG.noise.canvas) {
    var ctx2dProtos = [];
    if (typeof CanvasRenderingContext2D !== 'undefined') ctx2dProtos.push(CanvasRenderingContext2D.prototype);
    if (typeof OffscreenCanvasRenderingContext2D !== 'undefined') ctx2dProtos.push(OffscreenCanvasRenderingContext2D.prototype);
    ctx2dProtos.forEach(function (P) {
      patchMethod(P, 'getImageData', function (orig) {
        return function (sx, sy) {
          var img = _apply(orig, this, arguments);
          try { noiseRGBA(img.data, img.width, sx | 0, sy | 0, 0x43414E); } catch (e) { /* ignore */ }
          return img;
        };
      });
    });
    // toDataURL / toBlob / convertToBlob encode a *noisy copy*; the source
    // canvas itself is never modified, so page rendering is unaffected.
    var noisyCopy = function (canvas) {
      try {
        var w = canvas.width, h = canvas.height;
        if (!w || !h || w * h > 16 * 1024 * 1024) return null;
        var c2 = G.document ? G.document.createElement('canvas') : new OffscreenCanvas(w, h);
        c2.width = w; c2.height = h;
        var ctx = c2.getContext('2d');
        ctx.drawImage(canvas, 0, 0);
        var img = ctx.getImageData(0, 0, w, h); // noised by the patch above
        ctx.putImageData(img, 0, 0);
        return c2;
      } catch (e) { return null; } // tainted etc.: fall back to the native path
    };
    if (typeof HTMLCanvasElement !== 'undefined') {
      ['toDataURL', 'toBlob'].forEach(function (k) {
        patchMethod(HTMLCanvasElement.prototype, k, function (orig) {
          return function () { return _apply(orig, noisyCopy(this) || this, arguments); };
        });
      });
    }
    if (typeof OffscreenCanvas !== 'undefined') {
      patchMethod(OffscreenCanvas.prototype, 'convertToBlob', function (orig) {
        return function () { return _apply(orig, noisyCopy(this) || this, arguments); };
      });
    }
  }

  // ----------------------------------------------------------------- audio
  // Multiplicative, sparse and deterministic: silence stays *exactly* silence
  // (detectors render a 0 Hz oscillator and expect all zeros / -Infinity), and
  // getChannelData / copyFromChannel always agree because copyFromChannel is
  // routed through the same in-place noising. Only buffers produced by an audio
  // *render* are noised: a buffer the page built and filled itself must read
  // back exactly what was written (detectors probe precisely that).
  if (CFG.noise && CFG.noise.audio) {
    var noised = new _WeakSet();
    var rendered = new _WeakSet();
    var markRendered = function (buffer) { try { if (buffer) rendered.add(buffer); } catch (e) { /* ignore */ } return buffer; };
    if (typeof OfflineAudioContext !== 'undefined') {
      patchMethod(OfflineAudioContext.prototype, 'startRendering', function (orig) {
        return function () {
          var promise = _apply(orig, this, arguments);
          try { promise.then(markRendered, function () {}); } catch (e) { /* ignore */ }
          return promise;
        };
      });
    }
    if (typeof OfflineAudioCompletionEvent !== 'undefined') {
      patchGetter(OfflineAudioCompletionEvent.prototype, 'renderedBuffer', function (buffer) { return markRendered(buffer); });
    }
    var jitterBuffer = function (arr, owner) {
      if (!arr || !arr.length || noised.has(arr) || !rendered.has(owner)) return;
      noised.add(arr);
      for (var i = 0; i < arr.length; i += 61) {
        var v = arr[i];
        if (v !== 0 && v === v && v !== Infinity && v !== -Infinity) {
          arr[i] = v * (1 + (((mix(SEED ^ 0x41554449, i) & 0xFFFF) / 65535) - 0.5) * 2e-7);
        }
      }
    };
    if (typeof AudioBuffer !== 'undefined') {
      patchMethod(AudioBuffer.prototype, 'getChannelData', function (orig) {
        return function () {
          var data = _apply(orig, this, arguments);
          try { jitterBuffer(data, this); } catch (e) { /* ignore */ }
          return data;
        };
      });
      patchMethod(AudioBuffer.prototype, 'copyFromChannel', function (orig) {
        return function (destination, channelNumber) {
          try { this.getChannelData(channelNumber | 0); } catch (e) { /* invalid channel: native copy reports it */ }
          return _apply(orig, this, arguments);
        };
      });
    }
    if (typeof AnalyserNode !== 'undefined') {
      ['getFloatFrequencyData', 'getFloatTimeDomainData'].forEach(function (k) {
        patchMethod(AnalyserNode.prototype, k, function (orig) {
          return function (arr) {
            var r = _apply(orig, this, arguments);
            try {
              if (arr && arr.length) {
                for (var i = 0; i < arr.length; i += 53) {
                  var v = arr[i];
                  if (v !== 0 && v === v && v !== Infinity && v !== -Infinity) {
                    arr[i] = v + (((mix(SEED ^ 0x414E41, i) & 0xFFFF) / 65535) - 0.5) * 1e-4;
                  }
                }
              }
            } catch (e) { /* ignore */ }
            return r;
          };
        });
      });
    }
  }
})(__CFG__);
//# sourceURL=__TOKEN__
