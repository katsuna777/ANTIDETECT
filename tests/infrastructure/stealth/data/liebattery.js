(() => {
  const IS_BLINK = true, IS_GECKO = false, IS_WEBKIT = false, HAS_REFLECT = true;
  const RAND = 'r' + Math.random().toString(36).slice(-7);
  const isTypeError = (err) => err.constructor.name == 'TypeError';
  function failsTypeError({ spawnErr, withStack, final }) {
    try { spawnErr(); throw Error(); } catch (err) { if (!isTypeError(err)) return true; return withStack ? withStack(err) : false; } finally { final && final(); }
  }
  function failsWithError(fn) { try { fn(); return false; } catch (err) { return true; } }
  const hasKnownToString = (name) => ({ [`function ${name}() { [native code] }`]: true, [`function get ${name}() { [native code] }`]: true, [`function () { [native code] }`]: true });
  const hasValidStack = (err, reg, i = 1) => i === 0 ? reg.test(err.message) : reg.test(err.stack.split('\n')[i]);
  const AT_FUNCTION = /at Function\.toString /, AT_OBJECT = /at Object\.toString/;
  const FUNCTION_INSTANCE = /at (Function\.)?\[Symbol.hasInstance\]/, PROXY_INSTANCE = /at (Proxy\.)?\[Symbol.hasInstance\]/;
  function queryLies({ scope, apiFunction, proto, obj, lieProps }) {
    const name = apiFunction.name.replace(/get\s/, '');
    const objName = obj && obj.name;
    const nativeProto = Object.getPrototypeOf(apiFunction);
    let lies = {
      'failed illegal error': !!obj && failsTypeError({ spawnErr: () => obj.prototype[name] }),
      'failed undefined properties': (!!obj && /^(screen|navigator)$/i.test(objName) && !!(Object.getOwnPropertyDescriptor(self[objName.toLowerCase()], name) || Reflect.getOwnPropertyDescriptor(self[objName.toLowerCase()], name))),
      'failed call interface error': failsTypeError({ spawnErr: () => { new apiFunction(); apiFunction.call(proto); } }),
      'failed apply interface error': failsTypeError({ spawnErr: () => { new apiFunction(); apiFunction.apply(proto); } }),
      'failed new instance error': failsTypeError({ spawnErr: () => new apiFunction() }),
      'failed class extends error': !IS_WEBKIT && failsTypeError({ spawnErr: () => { class Fake extends apiFunction {} } }),
      'failed null conversion error': failsTypeError({ spawnErr: () => Object.setPrototypeOf(apiFunction, null).toString(), final: () => Object.setPrototypeOf(apiFunction, nativeProto) }),
      'failed toString': (!hasKnownToString(name)[scope.Function.prototype.toString.call(apiFunction)] || !hasKnownToString('toString')[scope.Function.prototype.toString.call(apiFunction.toString)]),
      'failed "prototype" in function': 'prototype' in apiFunction,
      'failed descriptor': !!(Object.getOwnPropertyDescriptor(apiFunction, 'arguments') || Reflect.getOwnPropertyDescriptor(apiFunction, 'arguments') || Object.getOwnPropertyDescriptor(apiFunction, 'caller') || Reflect.getOwnPropertyDescriptor(apiFunction, 'caller') || Object.getOwnPropertyDescriptor(apiFunction, 'prototype') || Reflect.getOwnPropertyDescriptor(apiFunction, 'prototype') || Object.getOwnPropertyDescriptor(apiFunction, 'toString') || Reflect.getOwnPropertyDescriptor(apiFunction, 'toString')),
      'failed own property': !!(apiFunction.hasOwnProperty('arguments') || apiFunction.hasOwnProperty('caller') || apiFunction.hasOwnProperty('prototype') || apiFunction.hasOwnProperty('toString')),
      'failed descriptor keys': (Object.keys(Object.getOwnPropertyDescriptors(apiFunction)).sort().toString() != 'length,name'),
      'failed own property names': (Object.getOwnPropertyNames(apiFunction).sort().toString() != 'length,name'),
      'failed own keys names': HAS_REFLECT && (Reflect.ownKeys(apiFunction).sort().toString() != 'length,name'),
      'failed object toString error': (failsTypeError({ spawnErr: () => Object.create(apiFunction).toString(), withStack: (err) => IS_BLINK && !hasValidStack(err, AT_FUNCTION) }) || failsTypeError({ spawnErr: () => Object.create(new Proxy(apiFunction, {})).toString(), withStack: (err) => IS_BLINK && !hasValidStack(err, AT_OBJECT) })),
      'failed at incompatible proxy error': failsTypeError({ spawnErr: () => { apiFunction.arguments; apiFunction.caller; } }),
      'failed at toString incompatible proxy error': failsTypeError({ spawnErr: () => { apiFunction.toString.arguments; apiFunction.toString.caller; } }),
      'failed at too much recursion error': failsTypeError({ spawnErr: () => { Object.setPrototypeOf(apiFunction, Object.create(apiFunction)).toString(); }, final: () => Object.setPrototypeOf(apiFunction, nativeProto) }),
    };
    return Object.keys(lies).filter(k => !!lies[k]);
  }
  const apis = [
    [WebGLRenderingContext, 'getParameter'], [WebGLRenderingContext, 'getExtension'], [WebGLRenderingContext, 'getSupportedExtensions'], [WebGLRenderingContext, 'readPixels'],
    [WebGL2RenderingContext, 'getParameter'], [HTMLCanvasElement, 'toDataURL'], [HTMLCanvasElement, 'toBlob'], [CanvasRenderingContext2D, 'getImageData'],
    [Screen, 'availWidth'], [Screen, 'availHeight'], [Screen, 'availTop'], [Screen, 'width'],
    [AudioBuffer, 'getChannelData'], [AnalyserNode, 'getFloatFrequencyData'], [Navigator, 'deviceMemory'], [Navigator, 'platform'], [Navigator, 'hardwareConcurrency'], [Navigator, 'userAgent'],
    [NavigatorUAData, 'platform'], [Date, 'getTimezoneOffset'], [Function, 'toString'],
  ];
  // nested-iframe scope like CreepJS "behemoth iframe"
  const mk = () => { const d = document.createElement('div'); d.style.cssText = 'position:absolute;left:-9999px'; d.innerHTML = '<div><iframe></iframe></div>'; document.body.appendChild(d); const f = d.querySelector('iframe').contentWindow; const d2 = f.document.createElement('div'); d2.innerHTML = '<div><iframe></iframe></div>'; f.document.body.appendChild(d2); return d2.querySelector('iframe').contentWindow; };
  const scope = mk();
  const out = {};
  for (const [obj, name] of apis) {
    try {
      const proto = obj.prototype || obj;
      let fn, isGetter = false;
      try { fn = proto[name]; } catch (e) { fn = undefined; }
      if (typeof fn !== 'function') { const d = Object.getOwnPropertyDescriptor(proto, name); fn = d && d.get; isGetter = true; }
      if (typeof fn !== 'function') { out[obj.name + '.' + name] = 'n/a'; continue; }
      out[obj.name + '.' + name] = queryLies({ scope, apiFunction: fn, proto, obj: isGetter ? obj : null, lieProps: {} });
    } catch (e) { out[obj.name + '.' + name] = 'EXC ' + e.message; }
  }
  return JSON.stringify(Object.fromEntries(Object.entries(out).filter(([k, v]) => !(Array.isArray(v) && v.length === 0))));
})()
