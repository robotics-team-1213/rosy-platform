# Pilot 전체 브라우저 회귀 — LOCAL

**판정: Pilot 브라우저 회귀 통과, G2/G3 수용은 HOLD.** Windows 호스트의 로컬 가짜 CORE와 Chromium에서 `ROSY_RUN_BROWSER_TESTS=1 python -m pytest middleware/ui/pilot/test/test_pilot_browser.py -q -rfE -p no:cacheprovider`를 실행했다. 결과는 **108 passed** (475.43초), `test/known_failures.py` **0 NEW**였다. 원본 로그는 `X:/DevTemp/pilot-full-current/run.txt`, SHA256 `14b21b225f06405cb57274c4ac45d915a1d7360586738a984f71f9969a569f9d`이다.

실행 중 공유 `main`은 `80355bb03`에서 `db006d7cf`로 이동했다. `git diff --name-only 80355bb03 db006d7cf`는 `docs/validation/uiux-site-g3-readiness-2026-10-07/result.md` 하나만 보였고, Pilot 코드·시험 파일은 동일했다. 따라서 이 회귀 결과는 두 커밋의 같은 Pilot 트리에 적용되지만, 실행 중 공유 체크아웃의 전체 저장소 SHA가 고정되었다고 주장하지 않는다.

시험은 연결 게이트, 주행 HUD·카메라·정지, 재접속, 로봇 녹화본, 팔·그리퍼 등 브라우저 경로를 확인한다. 모든 선언 상태×폭의 G2 캡처, 실물 Lenovo 태블릿·로봇 readback, 요청자의 G3 여덟 항목을 대체하지 않는다. 제품 전체는 **HOLD**다.
