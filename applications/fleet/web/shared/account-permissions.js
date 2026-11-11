export function canManageAccounts(session) {
  return session?.via === 'cookie' && !!session.account_id && !session.password_change_required
    && Array.isArray(session.grants) && session.grants.some(grant => grant.resource === session.site_resource
      && grant.capabilities.includes('accounts.manage'));
}

export function canViewAccountSetup(session) {
  return canManageAccounts(session) || (session?.via === 'cookie' && !session.account_id
    && !session.password_change_required && session.role === 'policy-admin');
}

// D-955 team default: operate the site, every robot and every project; no account, policy,
// camera, robot-admin or learning approval/publish/manage rights.
export function teamGrants(siteResource) {
  return [
    {resource: siteResource, capabilities: ['fleet.read', 'fleet.operate', 'games.operate', 'monitoring.read',
      'harbor.view', 'harbor.operate', 'harbor.field']},
    {resource: 'robot:*', capabilities: ['robot.read', 'robot.operate']},
    {resource: 'project:*', capabilities: ['learning.view', 'learning.edit', 'learning.import']},
  ];
}

// Choosing a role fills the editor with its bundle; the server still checks only the stored grants.
export function roleGrants(role, siteResource) {
  if (role === 'viewer') {
    return [{resource: siteResource, capabilities: ['fleet.read', 'monitoring.read', 'harbor.view']}, {resource: 'robot:*', capabilities: ['robot.read']},
      {resource: 'project:*', capabilities: ['learning.view']}];
  }
  if (role === 'policy-admin') {
    return [[siteResource, 'site'], ['robot:*', 'robot'], ['project:*', 'project']]
      // Vault retired 2026-10-24; its rights stay grantable by hand only.
      .map(([resource, kind]) => ({resource, capabilities: Object.keys(CAPABILITIES[kind]).filter(c => !c.startsWith('vault.'))}));
  }
  return teamGrants(siteResource);
}

export const CAPABILITIES = {
  site: {'accounts.manage': '계정 관리', 'fleet.read': '관제 조회', 'fleet.operate': '관제 조작',
    'fleet.policy': '관제 정책', 'camera.manage': '카메라 관리', 'games.operate': '게임 조작',
    'calibration.operate': '보정 실측 답', 'monitoring.read': 'Monitoring 조회',
    'harbor.view': 'Harbor 조회', 'harbor.operate': 'Harbor 운영', 'harbor.field': 'Harbor 현장', 'harbor.admin': 'Harbor 관리',
    'vault.read': 'Vault 조회', 'vault.operate': 'Vault 조작', 'vault.manage': 'Vault 장부 정리'},
  robot: {'robot.read': '로봇 조회', 'robot.operate': '로봇 조작', 'robot.admin': '로봇 관리'},
  project: {'learning.view': '학습 조회', 'learning.edit': '학습 편집', 'learning.approve': '학습 승인',
    'learning.manage': '프로젝트 관리', 'learning.import': '데이터 가져오기', 'learning.publish': '모델 게시'},
};
