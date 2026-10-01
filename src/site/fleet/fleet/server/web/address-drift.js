// 고정 주소가 지금 망에 있는지(GET /api/fleet/discovery/addresses)를 운용자 문장으로 옮긴다.
// Fleet → CORE는 평문이라 주소를 따라가지 않는다(D-361 3, D-370 5.3). 여기는 까닭을 말하고,
// 옮기기는 기존 로봇별 "새 주소로 옮기기"(서버가 토큰으로 신원을 다시 확인)만 부른다.
// DOM 없는 순수 함수만 둔다(node 시험 대상).

import { messageFor } from "./enrollment.js";

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

// "새 주소로 옮기기 (전체)" 대상: 서버가 옮길 수 있다고 한 등록 로봇만(새 주소가 하나, 등록부 address_changed).
export function bulkMoveTargets(payload) {
  return (payload?.robots || []).filter((entry) => entry.movable && entry.origin === "enrolled");
}

// 한 번의 확인으로 여러 대를 옮기므로 대상과 새 주소를 모두 적는다. 신원 확인은 줄지 않는다.
export function bulkConfirmMessage(targets) {
  const pairs = targets.map((entry) => `"${entry.robot_id}" → ${entry.seen_addresses[0]}`).join(", ");
  return `${pairs} — 로봇 ${targets.length}대를 새 주소로 옮길까요? 로봇마다 Fleet이 새 주소에서 신원을 `
    + "다시 확인하고, 다른 기기가 답하면 그 로봇만 옮기지 않고 새 코드가 필요해집니다.";
}

// 한 대씩 차례로, 로봇별 이동과 같은 요청(move)으로 보낸다. 한 대가 실패해도 나머지는 간다.
// move(robot_id)는 실패하면 { detail }을 가진 오류를 던진다.
export async function runBulkMove(targets, move) {
  const results = [];
  for (const entry of targets) {
    try {
      await move(entry.robot_id);
      results.push({ robot_id: entry.robot_id, ok: true,
        lines: [`${entry.robot_id}: ${entry.seen_addresses[0]}(으)로 옮김`] });
    } catch (err) {
      const [first, ...rest] = messageFor(err?.detail || {});
      results.push({ robot_id: entry.robot_id, ok: false, lines: [`${entry.robot_id}: ${first}`, ...rest] });
    }
  }
  return results;
}
