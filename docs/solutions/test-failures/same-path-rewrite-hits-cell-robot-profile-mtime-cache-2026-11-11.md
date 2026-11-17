---
symptom: "OMX 프로파일 동일성 시험이 묶음·단독 모두 실패하고 main에선 우연히 통과한다 — before == after 해시"
discovered: 2026-11-11
category: test-failures
tags: [omx, session-caps, profile, cache, flaky-test, landing-gate]
---

# 같은 경로를 즉시 다시 쓰는 시험은 `cell_robot_profile.load`의 (경로, mtime, 크기) 캐시에 걸린다

## 증상

`test/test_omx_session_caps_layers.py::test_the_servo_is_part_of_the_profile_identity`가
착지(FULL 사전시험)에서 실패했다 — `before == after`로 서로 다른 servo 값의
`profile_sha256`이 같게 나왔다. 단독 재시험(D-790)도 실패, main에서의 MAIN-RED 재시험은
통과해 브랜치 탓으로 분류되어 착지가 멈췄다. 실제로는 브랜치와 무관한 시험 결함이다.

## 원인

`deploy/robot/omx/cell_robot_profile.py`의 `load()`는 모듈 수준 `_PROFILE_CACHE`를
`(경로, st_mtime_ns, st_size)` 키로 쓴다. 시험이 **같은 경로**에 `{"i": 50}` → `{"i": 60}`을
마이크로초 간격으로 다시 썼다. 두 직렬화 길이는 같고, 다시 쓰는 틱이 파일시스템 mtime
정밀도보다 짧으면 `(경로, mtime, 크기)`가 충돌해 **첫 로드의 해시가 캐시로 돌아온다.**
호스트 부하에 따라 같은 틱에 걸리거나 안 걸리므로 묶음·단독 실패 후 main 통과라는
비결정적 모습이 나타났다.

## 해결

시험이 서로 다른 파일 이름(`i50.json` / `i60.json`)에 프로파일을 쓰게 했다
(커밋 5f08a79b4c). 같은 tmp_path 안이라 `operating_envelope_path`·`work_dir`의
resolve 결과는 같고, 해시 차이는 servo 값만 남는다 — 캐시 키가 경로로 갈라져
mtime 정밀도와 무관해진다. `load()`와 캐시 정책은 그대로다(운영 동작 불변).

## 검증 근거

- 실패: 착지 로그 `land-fix-trail-recovery-20261111074720.log`의
  `alone-pre-pre-28-2.txt`(단독 실패, exit 1)와 main 30e31575e9 재시험 통과.
- 수정 후: 원격(ai 호스트, 커밋 477da4687d) `test_omx_session_caps_layers.py` +
  `test_module_structure.py` 58 passed, 0 failed, known_failures 0 new.

## 재발 방지

- 같은 캐시를 쓰는 로더를 시험할 때는 **재작성이 아니라 서로 다른 경로**로 비교한다.
- `(경로, mtime, 크기)` 캐시 키는 길이가 같은 즉시 재작성과 충돌한다 — 이 로더를
  재사용하는 새 시험에서도 마찬가지다.
- 착지 관문이 「브랜치 탓」으로 분류한 NEW 실패라도, 건드린 파일과 무관하면 캐시·타이밍
  충돌을 의심하고 로더의 캐시 키부터 읽는다.

## 다음에 적용할 조건

`cell_robot_profile.load`(또는 이 형태의 mtime 키 캐시)를 시험하는 모든 코드;
착지 관문 NEW 실패 분류가 트리거.
