// D-991 /console/maintenance: PC 상태·조치·이력. 해도 되는지는 그 PC의 도우미가 판단한다.
import {createFleetClient} from '/common/fleet-client.js';
import {createPageScope} from '/common/scope.js';
import {confirmIrreversible} from '/common/ui.js';
import {developmentToken} from '/console/assets/development-auth.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {bindTokenAccess, classifyAuthFailure, writeStoredToken} from '/console/assets/fleet-session.js';
import {createHostServices} from '/console/assets/host-services.js';
import {createDbMaintenance} from '/console/assets/db-maintenance.js';

const pageScope = createPageScope();
const request = createFleetClient({credential: () => access.getToken(), origin: location.origin});
const access = bindTokenAccess({
  scope: pageScope,
  onCredential: (nextToken, credentialChange) => {
    void connect(credentialChange);
  },
});

bindEstop(request, {listen: (node, type, fn) => pageScope.listen(node, type, fn), life: () => pageScope.capture()});
bindTopbarToggle((node, type, fn) => pageScope.listen(node, type, fn));
tickClock();
pageScope.interval(tickClock, 1000);
watchFleet(request, {scope: pageScope});

const call = (url, options) => {
  const life = pageScope.capture();
  return request(url, {
    ...(options && {
      method: options.method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(options.body),
    }),
    signals: [life.signal],
  });
};
const view = createHostServices({root: document.getElementById('host-services'), call, confirmIrreversible});
const dbRoot = document.getElementById('db-maintenance');
const dbView = dbRoot ? createDbMaintenance({root: dbRoot, call}) : null;

async function connect(credentialChange = false) {
  const life = pageScope.capture();
  try {
    const session = await request('/api/fleet/auth/session', {signals: [life.signal]});
    life.check();
    document.getElementById('maintenance-login').hidden = true;
    showSession(session, {credentialChange});
    access.refreshLogin(false);
    await Promise.all([view.refresh(), dbView ? dbView.refresh() : Promise.resolve()]);
  } catch (error) {
    if (error?.name === 'AbortError' || !life.current()) return;
    const failure = classifyAuthFailure(error);
    document.getElementById('maintenance-login').hidden = !failure.offerLogin;
    if (failure.signOut) {
      if (failure.offerLogin) writeStoredToken('');
      showSignedOut({refused: failure.refused});
      if (failure.offerLogin) access.refreshLogin(true);
    }
  }
}

pageScope.interval(() => {
  if (!document.hidden) {
    view.refresh().catch(() => {});
    if (dbView) dbView.refresh().catch(() => {});
  }
}, 30000);
pageScope.listen(document, 'visibilitychange', () => {
  if (!document.hidden) {
    view.refresh().catch(() => {});
    if (dbView) dbView.refresh().catch(() => {});
  }
});
pageScope.onResume(() => { void connect(false); });
void access.bootstrap({
  developmentToken,
  connect: (changed) => connect(changed),
  onSignedOut: () => {
    document.getElementById('maintenance-login').hidden = false;
    showSignedOut();
    access.refreshLogin(true);
  },
});
