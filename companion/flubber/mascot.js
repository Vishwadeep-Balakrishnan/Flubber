(() => {
  if (globalThis.__flubberOverlayV2) return;
  const png = __FLUBBER_IMAGE__;
  let host = null, style = null, surface = null, ring = null, touched = 0, timer = null;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  async function ensure() {
    if (host?.isConnected) {
      if (style && !document.adoptedStyleSheets.includes(style)) document.adoptedStyleSheets = [...document.adoptedStyleSheets, style];
      return;
    }
    host = document.createElement('div');
    host.setAttribute('data-flubber-overlay', '');
    host.setAttribute('aria-hidden', 'true');
    host.inert = true;
    host.style.cssText = 'all:initial!important;position:fixed!important;left:0!important;top:0!important;width:0!important;height:0!important;z-index:2147483647!important;pointer-events:none!important;display:block!important;';
    const shadow = host.attachShadow({mode: 'closed'});
    surface = document.createElement('canvas');
    surface.width = surface.height = 128;
    surface.style.cssText = 'position:absolute;width:36px;height:36px;left:-18px;top:-18px;pointer-events:none;filter:drop-shadow(0 3px 4px #183c8530);';
    if (!reduceMotion) surface.style.transition = 'transform 100ms ease-out';
    ring = document.createElement('div');
    ring.style.cssText = 'position:absolute;width:40px;height:40px;left:-20px;top:-20px;border:2px solid #185bcd;border-radius:50%;box-sizing:border-box;opacity:0;pointer-events:none;';
    shadow.append(ring, surface);
    style = new CSSStyleSheet();
    style.replaceSync('html[data-flubber-controlling],html[data-flubber-controlling] *{cursor:none!important}');
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, style];
    document.documentElement.append(host);
    const bytes = Uint8Array.from(atob(png), c => c.charCodeAt(0));
    // Decode locally to a canvas; no image URL, network request, or page-CSP bypass.
    const image = await createImageBitmap(new Blob([bytes], {type: 'image/png'}));
    surface.getContext('2d').drawImage(image, 0, 0, 128, 128);
    image.close();
    if (!timer) timer = setInterval(() => {if (Date.now() - touched > 20000) destroy();}, 2000);
  }
  async function move(x, y, kind = 'move') {
    await ensure();
    touched = Date.now();
    document.documentElement.setAttribute('data-flubber-controlling', '');
    host.style.setProperty('display', 'block', 'important');
    x = Math.max(2, Math.min(innerWidth - 2, Number(x) || innerWidth / 2));
    y = Math.max(2, Math.min(innerHeight - 2, Number(y) || innerHeight / 2));
    surface.style.transform = `translate(${x}px,${y}px)`;
    ring.style.transform = `translate(${x}px,${y}px)`;
    ring.style.opacity = kind === 'click' ? '.45' : '0';
    if (!reduceMotion) await new Promise(resolve => setTimeout(resolve, 105));
  }
  function visible(value) {
    if (host) host.style.setProperty('display', value ? 'block' : 'none', 'important');
  }
  function destroy() {
    host?.remove();
    if (style) document.adoptedStyleSheets = document.adoptedStyleSheets.filter(sheet => sheet !== style);
    host = style = surface = ring = null;
    document.documentElement.removeAttribute('data-flubber-controlling');
    if (timer) clearInterval(timer);
    timer = null;
  }
  globalThis.__flubberOverlayV2 = {move, visible, destroy};
})();
