const DOCUMENTS = new Set(['/console', '/console/install', '/console/site-map', '/console/cell', '/console/profile', '/console/accounts', '/console/policy']);

// Login can only return to a Fleet document on this origin, never to credentials or another service.
export function loginReturn(value, origin) {
  try {
    const url = new URL(value || '/console', origin);
    if (url.origin === origin && !url.username && !url.password && !url.hash && url.pathname === '/api/fleet/auth/authorize') {
      const fields = ['response_type', 'client_id', 'redirect_uri', 'scope', 'state', 'code_challenge', 'code_challenge_method'];
      if ([...url.searchParams.keys()].length !== fields.length || fields.some(key => url.searchParams.getAll(key).length !== 1)
        || url.search.length > 4096 || url.searchParams.get('response_type') !== 'code'
        || url.searchParams.get('code_challenge_method') !== 'S256'
        || !/^[A-Za-z0-9_-]{43}$/.test(url.searchParams.get('code_challenge'))
        || !url.searchParams.get('state')) return '/console';
      return url.pathname + url.search; // The authority revalidates registered client, redirect and resource.
    }
    if (url.origin !== origin || url.username || url.password || !DOCUMENTS.has(url.pathname)) return '/console';
    const query = new URLSearchParams();
    if (url.pathname === '/console/profile' && url.searchParams.has('return')) {
      const back = new URL(url.searchParams.get('return'), origin);
      query.set('return', back.pathname === '/console/profile' ? '/console' : loginReturn(back.href, origin));
    }
    if (url.pathname === '/console') {
      const view = url.searchParams.get('view'), show = url.searchParams.get('show');
      if (view === 'work' || view === 'records') query.set('view', view);
      if (query.has('view') && ['pending', 'done', 'new', 'open', 'closed', 'facts', 'log'].includes(show)) query.set('show', show);
      if (url.searchParams.get('inbox') === '1') query.set('inbox', '1');
      const transfer = url.searchParams.getAll('arm_transfer');
      if (view === 'work' && transfer.length === 1 && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$/.test(transfer[0])) query.set('arm_transfer', transfer[0]);
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
