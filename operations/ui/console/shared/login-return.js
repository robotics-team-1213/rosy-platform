const DOCUMENTS = new Set(['/console', '/console/install', '/console/site-map', '/console/cell', '/console/profile']);

// Login can only return to a Fleet document on this origin, never to credentials or another service.
export function loginReturn(value, origin) {
  try {
    const url = new URL(value || '/console', origin);
    if (url.origin !== origin || url.username || url.password || !DOCUMENTS.has(url.pathname)) return '/console';
    const query = new URLSearchParams();
    if (url.pathname === '/console/profile' && url.searchParams.has('return')) {
      const back = new URL(url.searchParams.get('return'), origin);
      query.set('return', back.pathname === '/console/profile' ? '/console' : loginReturn(back.href, origin));
    }
    if (url.pathname === '/console') {
      if (url.searchParams.get('view') === 'work') query.set('view', 'work');
      if (url.searchParams.get('inbox') === '1') query.set('inbox', '1');
    }
    const robot = url.searchParams.get('robot');
    if (['/console', '/console/site-map'].includes(url.pathname) && /^[a-zA-Z0-9_-]{1,128}$/.test(robot || '')) {
      query.set('robot', robot);
    }
    const anchor = url.pathname === '/console/site-map' && url.hash === '#teach-heading' ? url.hash : '';
    return url.pathname + (query.size ? '?' + query : '') + anchor;
  } catch { return '/console'; }
}

export function loginHref(location) {
  return '/console/login?return=' + encodeURIComponent(loginReturn(location.href, location.origin));
}
