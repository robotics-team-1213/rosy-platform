// 고정 주소가 지금 망에 있는지(GET /api/fleet/discovery/addresses)를 운용자 문장으로 옮긴다.
// Fleet → CORE는 평문이라 주소를 따라가지 않는다(D-361 3, D-370 5.3). 여기는 까닭을 말하고,
// 옮기기는 등록 패널의 "새 주소로 옮기기…"(로봇 화면 코드로 새 주소에서 재페어링)만 연다.
// DOM 없는 순수 함수만 둔다(node 시험 대상).

export function addressMap(payload) {
  const out = {};
  for (const entry of payload?.robots || []) out[entry.robot_id] = entry;
  return out;
}

// 로봇 카드에 붙일 까닭 한 줄과, 있으면 행동("move"). 모르는 상태는 짐작하지 않는다.
export function addressReason(entry) {
  if (!entry) return null;
  const seen = entry.seen_addresses || [];
  const file = entry.origin === "static";
  if (entry.status === "outside_scanned_subnets") {
    return {
      // /24로 어림한 판정이라 단정하지 않는다(address_drift.py docstring).
      text: `고정 주소 ${entry.pinned}이(가) 지금 망에 없을 수 있습니다 — `
        + (file ? "robots.yaml의 base_url을 확인하세요." : "로봇이 발견 목록에 다시 보이면 새 주소로 옮길 수 있습니다."),
      action: null,
    };
  }
  if (entry.status !== "seen_at_other_address") return null;
  if (seen.length > 1) {
    return { text: `같은 이름이 여러 주소(${seen.join(", ")})에 보입니다 — 신원 충돌이라 옮기지 않습니다.`, action: null };
  }
  if (file && entry.pinned_is_name) {
    return {
      text: `${entry.pinned}은(는) 이름이라 Fleet이 따라가지 않습니다 — 스캔에서 ${seen[0]}에 보입니다. `
        + "같은 로봇인지 확인한 뒤 robots.yaml의 base_url을 그 주소로 고치세요.",
      action: null,
    };
  }
  if (file) {
    return {
      text: `같은 로봇이 ${seen[0]}에 보입니다 — 확인한 뒤 robots.yaml의 base_url을 고치세요.`,
      action: null,
    };
  }
  if (entry.movable) {
    return { text: `같은 로봇이 ${seen[0]}에 보입니다 — 새 주소로 옮기기…`, action: "move" };
  }
  return { text: `같은 로봇이 ${seen[0]}에 보입니다 — 등록부가 주소 바뀜을 확인하면 옮길 수 있습니다.`, action: null };
}

export const RENUMBER_BANNER = "사이트 망 주소가 바뀌었을 수 있습니다 — IP로 고정된 로봇 주소가 모두 지금 스캔된 망 밖입니다. "
  + "같은 로봇이 새 주소에 보이면 로봇 화면 코드로 옮기고, 파일 로봇은 robots.yaml을 확인하세요.";

// 이름(.local)으로 고정된 로봇이 지금 연결돼 있으면 망 전체가 바뀐 것은 아니다 — 띄우지 않는다.
export function renumberBanner(payload, robots = []) {
  if (!payload?.all_outside) return null;
  const online = new Set(robots.filter((robot) => robot.online).map((robot) => robot.robot_id));
  const named = (payload.robots || []).filter((entry) => entry.pinned_is_name);
  return named.some((entry) => online.has(entry.robot_id)) ? null : RENUMBER_BANNER;
}

// 경보 묶음에 나열할 로봇: 서버가 옮길 수 있다고 한 등록 로봇만(새 주소가 하나, 등록부 address_changed).
// 한 번에 여러 대를 옮기지 않는다 — 옮기기마다 그 로봇의 화면 코드가 필요하다(D-361 2026-10-01).
export function movableRobots(payload) {
  return (payload?.robots || []).filter((entry) => entry.movable && entry.origin === "enrolled");
}
