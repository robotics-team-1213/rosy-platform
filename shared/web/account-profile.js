// Display-only account context. Authorization remains with the receiving service.
export function profileView(session) {
  if (session?.authenticated !== true || !session.account_id) return null;
  let url;
  try { url = new URL(session.profile_url); } catch { return null; }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash
      || url.pathname !== '/console/profile') return null;
  const profile = session.profile;
  const validName = typeof profile?.display_name === 'string' && profile.display_name.trim()
    && [...profile.display_name].length <= 80 && !/[\p{Cc}\p{Cs}]/u.test(profile.display_name);
  const name = profile?.account_id === session.account_id && validName ? profile.display_name : null;
  return {href: url.href, label: name ? `${name} · 내 계정` : '내 계정 · 이름 확인 불가'};
}

export function renderAccountProfile(session, root = document) {
  const view = root.documentElement?.dataset.pilotShell === 'android' ? null : profileView(session);
  for (const link of root.querySelectorAll('[data-account-profile]')) {
    link.hidden = !view;
    link.textContent = view?.label || '';
    if (view) {
      link.href = view.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    } else link.removeAttribute('href');
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('rosy:account-profile', event => renderAccountProfile(event.detail));
}
