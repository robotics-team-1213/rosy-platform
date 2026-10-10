// CAP-001 is evidence for presentation. CORE still decides every command.
export function capabilityReason(capabilities, feature) {
  if (capabilities === undefined) return ''; // Fleet versions before CAP-001 gather
  if (capabilities === null) return '주행 기능 확인 불가';
  let value = capabilities;
  for (const part of feature.split('.')) value = value?.[part];
  if (value === true) return '';
  if (capabilities.runtime?.mode === 'motor') return '수동 주행만 지원';
  if (capabilities.runtime?.mode === 'core') return '주행 런타임 대기';
  return feature === 'navigation.goal_navigation' ? '목표 주행 미지원' : '대형 주행 미지원';
}

export function formationReason(robots, leader, members) {
  const selected = [...new Set([leader, ...members])];
  if (!leader || selected.length < 2) return '리더와 팔로워를 고르세요';
  for (const id of selected) {
    const robot = robots.find(r => r.robot_id === id);
    if (!robot?.online) return `${id} · 로봇 오프라인`;
    const reason = capabilityReason(robot.capabilities, id === leader ? 'swarm.lead' : 'swarm.follow');
    if (reason) return `${id} · ${reason}`;
  }
  return '';
}

// Field check 2026-10-10: with only manual-only robots (CAP-001 runtime.maps.occupancy false) the console
// still asked /api/fleet/map every 30 s and logged a 404 each time. True only when every robot says so.
export function noRobotServesGrid(robots) {
  return robots.length > 0 && robots.every(robot => robot.capabilities?.runtime?.maps?.occupancy === false);
}
