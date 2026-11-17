// C14 행의 조용한 칸 글자(quietRowTexts): 알 수 없음은 행에 한 번(D-280), 지연 나이는 대표 칸(연결 태그)에만 한 번.
import {test} from "node:test";
import assert from "node:assert/strict";
import {blankRepeatedUnknown, quietRowTexts} from "../core_ui_logic.js";

const link = (state, ageS) => ({state, ageS});

test("지연 행의 같은 나이 접미는 하위 칸에서 빠지고 연결 칸에만 남는다", () => {
  assert.deepEqual(
    quietRowTexts(link("delayed", 30), ["82% · 30초 전", "C1 대기 · 30초 전", "C1 충전소 · 30초 전"]),
    ["82%", "C1 대기", "C1 충전소"],
  );
  // 소수 나이는 글자가 달라도 같은 초면 같은 사실이다(지우지 않으면 행에 나이가 둘로 보인다).
  assert.deepEqual(
    quietRowTexts(link("delayed", 12.5), ["82% · 12.5초 전", "정보 없음", "정보 없음"]),
    ["82%", "정보 없음", ""],
  );
});

test("단위가 다른 같은 나이(분·시간)도 지우고, 다른 나이는 단위를 환산해도 남긴다", () => {
  // 분 단위 같은 나이: 링크 600초와 칸 '10분 전'(600초)은 같은 사실이다.
  assert.deepEqual(
    quietRowTexts(link("delayed", 600), ["82% · 10분 전", "C1 대기 · 10분 전", "C1 충전소 · 10분 전"]),
    ["82%", "C1 대기", "C1 충전소"],
  );
  // 시간 단위 소수 나이: 1.5시간 = 5400초.
  assert.deepEqual(
    quietRowTexts(link("delayed", 5400), ["82% · 1.5시간 전"]),
    ["82%"],
  );
  // 링크 30초 대 칸 10분(600초): 다른 나이 — 전원의 10분 전 값은 사실이므로 남는다.
  assert.deepEqual(
    quietRowTexts(link("delayed", 30), ["82% · 10분 전", "운행 중"]),
    ["82% · 10분 전", "운행 중"],
  );
  // disconnected 링크는 나이를 말하지 않으므로 칸의 나이는 그대로다.
  assert.deepEqual(
    quietRowTexts(link("disconnected"), ["82% · 10분 전", "정보 없음"]),
    ["82% · 10분 전", "정보 없음"],
  );
});

test("칸의 나이가 다르거나 연결이 지연이 아니면 접미를 지우지 않는다", () => {
  assert.deepEqual(
    quietRowTexts(link("delayed", 30), ["82% · 31초 전", "x 1.00 · y 2.00 m", "운행 중"]),
    ["82% · 31초 전", "x 1.00 · y 2.00 m", "운행 중"],
  );
  assert.deepEqual(
    quietRowTexts(link("fresh", 0), ["82% · 30초 전", "대기", "충전소"]),
    ["82% · 30초 전", "대기", "충전소"],
  );
});

test("끊긴 행의 알 수 없음 표식은 행에 한 번만 남는다(D-280)", () => {
  assert.deepEqual(
    quietRowTexts(link("unavailable"), ["정보 없음", "정보 없음", "정보 없음"]),
    ["정보 없음", "", ""],
  );
  assert.deepEqual(
    blankRepeatedUnknown(["확인 불가", "충전소 A", "정보 없음"]),
    ["확인 불가", "충전소 A", ""],
  );
});

test("같은 나이가 여러 칸에 있으면 첫 칸에만 남기고, 다른·유일한 나이는 지우지 않는다", () => {
  assert.deepEqual(
    quietRowTexts(link("disconnected"), ["Cell B · S5 · 12초 전", "READY · 12초 전"]),
    ["Cell B · S5 · 12초 전", "READY"],
  );
  assert.deepEqual(
    quietRowTexts(link("disconnected"), ["Cell B · 12초 전", "READY · 30초 전"]),
    ["Cell B · 12초 전", "READY · 30초 전"],
  );
  assert.deepEqual(
    quietRowTexts(link("delayed", 30), ["82% · 30초 전", "C1 대기 · 30초 전", "C1 충전소 · 10분 전"]),
    ["82%", "C1 대기", "C1 충전소 · 10분 전"],
  );
});
