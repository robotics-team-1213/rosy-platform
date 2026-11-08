// D-991 /console/maintenance: PC 상태·조치·이력. 해도 되는지는 그 PC의 도우미가 판단한다.
import {createFleetClient} from '/common/fleet-client.js';
import {confirmIrreversible} from '/common/ui.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {createHostServices} from '/console/assets/host-services.js';

// A development or token session lives in this tab's storage, not a cookie (same as the other work pages).
const token = sessionStorage.getItem('rosy-console-token') || '';
const request = createFleetClient({credential: () => token, origin: location.origin});
bindEstop(request);
bindTopbarToggle();
tickClock();
setInterval(tickClock, 1000);
watchFleet(request);

const call = (url, options) => request(url, options && {
  method: options.method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(options.body),
});
const view = createHostServices({root: document.getElementById('host-services'), call, confirmIrreversible});

async function start() {
  try {
    showSession(await request('/api/fleet/auth/session'));
    await view.refresh();
  } catch (error) {
    if (error.status === 401) {
      document.getElementById('maintenance-login').hidden = false;
      showSignedOut();
    }
    return;
  }
  setInterval(() => { if (!document.hidden) view.refresh().catch(() => {}); }, 30000);
}
start();
