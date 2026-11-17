// 한 로봇 행의 알 수 없음 표식은 한 번만: 합침 규칙 blankRepeatedUnknown(D-280, 값 지어내기 금지).
// 규칙은 공용 순수 모듈(shared/web/core_ui_logic.js)로 옮겨갔다 — /common 로더 없이 단독 실행된다.
import test from "node:test";
import assert from "node:assert/strict";

const { blankRepeatedUnknown } = await import("../../../../shared/web/core_ui_logic.js");

test("끊긴 행의 알 수 없음 표식 세 번이 한 번으로 합쳐진다", () => {
  assert.deepEqual(
    blankRepeatedUnknown(["정보 없음", "정보 없음", "정보 없음"]),
    ["정보 없음", "", ""],
  );
});

test("아는 값은 그대로 두고 반복된 알 수 없음만 합친다", () => {
  assert.deepEqual(
    blankRepeatedUnknown(["80% · 충전 중", "x 1.00 · y 2.00 m", "운행 중"]),
    ["80% · 충전 중", "x 1.00 · y 2.00 m", "운행 중"],
  );
  assert.deepEqual(
    blankRepeatedUnknown(["정보 없음", "충전소 A", "정보 없음"]),
    ["정보 없음", "충전소 A", ""],
  );
  assert.deepEqual(
    blankRepeatedUnknown(["확인 불가", "정보 없음", "미확인"]),
    ["확인 불가", "", ""],
  );
});

test("문자열이 아니거나 비표식 문자열은 그대로 반환한다", () => {
  assert.deepEqual(blankRepeatedUnknown(["—", "지연 · 30초 전", null]), ["—", "지연 · 30초 전", null]);
});
