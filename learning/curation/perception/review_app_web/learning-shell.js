import {actionIcon} from '/common/ui.js';
import {mountLearningConnections} from '/learning-connections.js';

const shell = document.querySelector('ui-shell');
const body = shell?.querySelector('.ui-app-body');
const main = body?.querySelector('.ui-app-main');
if (shell && body && main) {
  shell.classList.add('learning-shell');
  const url = new URL(location.href);
  const review = url.pathname === '/' || url.pathname === '/pixels';
  const current = review ? 'review' : url.pathname === '/catalog' || url.pathname === '/accounts' ? 'data'
    : url.searchParams.get('view') === 'training' || url.pathname === '/learning/sim' ? 'training' : 'work';
  const destinations = [
    ['work', '작업', '/learning', 'list'],
    ['data', '자료', '/catalog', 'folder'],
    ['review', '검수', '/pixels?filter=pending', 'pixels'],
    ['training', '학습·결과', '/learning?view=training', 'history'],
  ];
  function link(label, href, icon, selected) {
    const anchor = document.createElement('a');
    anchor.textContent = label;
    anchor.href = href;
    if (selected) anchor.setAttribute('aria-current', 'page');
    if (icon) actionIcon(anchor, icon);
    return anchor;
  }
  const rail = body.querySelector(':scope > .ui-rail') || document.createElement('aside');
  rail.className = 'ui-rail learning-sidebar';
  const nav = document.createElement('nav');
  nav.className = 'learning-primary-nav';
  nav.setAttribute('aria-label', 'Learning 주 메뉴');
  for (const [key, label, href, icon] of destinations) {
    const anchor = link(label, href, icon, key === current);
    if (key === 'data') anchor.setAttribute('aria-label', '자료 등록');
    nav.append(anchor);
  }
  rail.replaceChildren(nav);
  const tools = document.createElement('details');
  tools.className = 'learning-tools';
  const summary = document.createElement('summary');
  summary.textContent = '작업 도구';
  const toolNav = document.createElement('nav');
  toolNav.setAttribute('aria-label', 'Learning 작업 도구');
  for (const [label, href, icon] of [
    ['카메라 맞춤', '/learning/camera', 'image'],
    ['OMX 구간 검수', '/learning/omx', 'robot'],
    ['SIM 실험', '/learning/sim', 'cell'],
  ]) toolNav.append(link(label, href, icon, url.pathname === href));
  tools.append(summary, toolNav);
  rail.append(tools);
  body.prepend(rail);
  body.dataset.seats = 'rail';

  const topbar = shell.querySelector('ui-topbar');
  if (topbar) {
    const brand = topbar.querySelector('ui-brand');
    if (brand) {
      brand.setAttribute('href', '/learning');
      brand.setAttribute('aria-label', 'Rosy Learning');
      const wordmark = brand.querySelector('b');
      if (wordmark) wordmark.textContent = 'Learning';
    }
    const context = document.createElement('span');
    context.className = 'learning-context';
    context.textContent = destinations.find(([key]) => key === current)[1];
    brand?.after(context);
    const connections = document.createElement('div');
    connections.className = 'learning-connections';
    const theme = topbar.querySelector('[data-theme-cycle]');
    if (theme) theme.before(connections);
    else topbar.append(connections);
    mountLearningConnections(connections);
  }

  if (review) {
    const subnav = document.createElement('nav');
    subnav.className = 'learning-review-nav';
    subnav.setAttribute('aria-label', '검수 종류');
    // Only editor selection belongs in cross-editor links; workflow query keys do not.
    subnav.append(link('객체 검수', '/', 'box', url.pathname === '/'),
      link('픽셀 검수', '/pixels', 'pixels', url.pathname === '/pixels'));
    function syncSelection() {
      const active = new URL(location.href);
      const selection = new URLSearchParams();
      for (const key of ['frame', 'filter']) if (active.searchParams.has(key)) selection.set(key, active.searchParams.get(key));
      const suffix = selection.size ? `?${selection}` : '';
      subnav.children[0].setAttribute('href', '/' + suffix);
      subnav.children[1].setAttribute('href', '/pixels' + suffix);
    }
    syncSelection();
    // Editors replace the URL after each selection without reloading the shell.
    for (const event of ['pointerdown', 'focusin', 'click']) subnav.addEventListener(event, syncSelection);
    const pathbar = main.querySelector('.ui-pathbar');
    if (pathbar) {
      pathbar.querySelector('h1')?.classList.add('sr-only');
      pathbar.append(subnav);
    } else main.prepend(subnav);
  }
  const pathbar = main.querySelector('.ui-pathbar');
  if (pathbar) {
    const compact = matchMedia('(width < 64rem)');
    const placeTools = () => (compact.matches ? pathbar : rail).append(tools);
    compact.addEventListener('change', placeTools);
    placeTools();
  }
}
