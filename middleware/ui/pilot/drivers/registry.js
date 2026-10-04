// 기기 종류 → 드라이버 등록부(D-323 T5). v1 등록분은 pinky_core 하나.
// OMX 로컬 컨트롤러의 teleop API 가 계약으로 확정되면 여기에 kind 를 하나 더
// 등록하는 것으로 확장한다(D-296 — 팔 최종 명령은 OMX 로컬 소유).

const drivers = new Map();

export function registerDriver(kind, driver) {
  if (!kind) throw new Error("driver kind is required");
  if (drivers.has(kind)) {
    if (drivers.get(kind) === driver) return;   // 같은 드라이버 재등록은 멱등(모듈 재주입 안전)
    throw new Error(`driver already registered: ${kind}`);
  }
  drivers.set(kind, driver);
}

export function driverFor(kind) {
  return drivers.get(kind) ?? null;
}

export function registeredKinds() {
  return [...drivers.keys()];
}
