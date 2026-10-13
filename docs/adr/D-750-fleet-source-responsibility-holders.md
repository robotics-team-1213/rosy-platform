## D-750 Fleet 서버 소스를 책임 폴더로 구분한다

**Status:** Accepted
**Date:** 2026-10-13

## Decision

D-738 S8: server/peer는 camera peer, cell은 셀 어댑터, auth는 등록·pairing·세션, console은 콘솔 조립·serving, ledger는 task·mission·trip·receipt 원장을 보관한다. 기존 channel 하위 폴더는 유지하며 app.py와 다른 별도 책임은 조립 root에 남긴다.

하위 holder에는 initializer를 만들지 않는다. source __path__와 기존 Fleet build helper가 기존 fleet.server.* 모듈을 연결하며 wheel에는 동일 이름으로 한 번만 설치한다. 중복 basename은 build를 거절한다. DB·프로세스·auth principal·claim/admission 거래·CORE 최종 명령 권한을 분리하거나 바꾸지 않는다.

| Previous ADR | Relationship |
|---|---|
| D-738 | S8 세부 source 책임 판정 |
| D-427 | source holder와 설치 identity 구분 |
| D-430 | source 이동의 독립 Safety 검토 |
| D-649 | 기존 Fleet build/sdist composition 재사용 |

## Verification

사용자 local merge-only 범위에서 source byte identity, standalone sdist→wheel identity, source imports, 독립 Safety/closure 및 lint를 확인한다. 원격 pytest·CI·이미지·장치는 NOT RUN이며 push하지 않는다.
