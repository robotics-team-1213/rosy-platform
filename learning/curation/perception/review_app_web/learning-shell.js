import {actionIcon} from '/common/ui.js';
import {mountLearningConnections} from '/learning-connections.js';

const shell = document.querySelector('ui-shell');
const body = shell?.querySelector('.ui-app-body');
const main = body?.querySelector('.ui-app-main');
if (shell && body && main) {
  shell.classList.add('learning-shell');
  const url = new URL(location.href);
  const review = url.pathname === '/' || url.pathname === '/pixels';
  const here = url.pathname === '/learning' && url.searchParams.get('view') === 'training' ? '/learning?view=training' : url.pathname;
  // D-857 §3: the menu is the loop stage; domains are filters inside each stage, not menus.
  const destinations = [
    ['home', '홈', '/learning', 'list'],
    ['data', '자료', '/catalog', 'folder'],
    ['truth', '정답', '/', 'pixels'],
    ['training', '학습', '/learning?view=training', 'history'],
    ['evaluate', '평가·승격', '/learning/evaluate', 'check'],
  ];
  // Every page belongs to one stage; a stage with several pages shows them as a sub-menu.
  const pages = {
    data: [['자료 등록', '/catalog', 'folder'], ['카메라 맞춤', '/learning/camera', 'image']],
    truth: [['객체 검수', '/', 'box'], ['픽셀 검수', '/pixels', 'pixels'], ['OMX 구간', '/learning/omx', 'robot'], ['VLM 판단', '/learning/vlm', 'check']],
    training: [['학습 실행', '/learning?view=training', 'history'], ['SIM 실험', '/learning/sim', 'cell']],
  };
  const current = here === '/accounts' ? 'data'  // Hugging Face imports are incoming data; the account itself is in settings.
    : (destinations.find(([key, , href]) => href === here || pages[key]?.some(([, page]) => page === here)) || destinations[0])[0];
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
    if (key === 'data') anchor.setAttribute('aria-label', '자료 등록');  // command search finds it from every page
    nav.append(anchor);
  }
  rail.replaceChildren(nav);
  body.prepend(rail);
  body.dataset.seats = 'rail';
  const stageLabel = destinations.find(([key]) => key === current)[1];

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
    context.textContent = stageLabel;
    brand?.after(context);
    const connections = document.createElement('div');
    connections.className = 'learning-connections';
    // D-857 §3: account and storage are settings, not loop stages.
    const settings = document.createElement('details');
    settings.className = 'learning-settings';
    const summary = document.createElement('summary');
    summary.textContent = '설정';
    actionIcon(summary, 'settings');
    const menu = document.createElement('div');
    menu.className = 'learning-settings-menu';
    menu.append(link('계정과 외부 자료', '/accounts', 'account', here === '/accounts'), link('저장 공간', '/learning#storage-panel', 'install'));
    settings.append(summary, menu);
    settings.addEventListener('keydown', event => { if (event.key === 'Escape' && settings.open) { settings.open = false; summary.focus(); } });
    document.addEventListener('click', event => { if (settings.open && !settings.contains(event.target)) settings.open = false; });
    const theme = topbar.querySelector('[data-theme-cycle]');
    if (theme) theme.before(connections, settings);
    else topbar.append(connections, settings);
    mountLearningConnections(connections);
  }

  if (pages[current]) {
    const subnav = document.createElement('nav');
    subnav.className = 'learning-review-nav';
    subnav.setAttribute('aria-label', `${stageLabel} 화면`);
    for (const [label, href, icon] of pages[current]) subnav.append(link(label, href, icon, href === here));
    if (review) {
      // Only editor selection belongs in cross-editor links; workflow query keys do not.
      const syncSelection = () => {
        const active = new URL(location.href);
        const selection = new URLSearchParams();
        for (const key of ['frame', 'filter']) if (active.searchParams.has(key)) selection.set(key, active.searchParams.get(key));
        const suffix = selection.size ? `?${selection}` : '';
        subnav.children[0].setAttribute('href', '/' + suffix);
        subnav.children[1].setAttribute('href', '/pixels' + suffix);
      };
      syncSelection();
      // Editors replace the URL after each selection without reloading the shell.
      for (const event of ['pointerdown', 'focusin', 'click']) subnav.addEventListener(event, syncSelection);
    }
    const pathbar = main.querySelector('.ui-pathbar');
    if (pathbar) {
      // The current sub-menu item names the page; the heading stays for screen readers.
      pathbar.querySelector('h1')?.classList.add('sr-only');
      pathbar.append(subnav);
    } else main.prepend(subnav);
  }
}
