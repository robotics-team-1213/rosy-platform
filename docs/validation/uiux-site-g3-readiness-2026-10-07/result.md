# ROSY UI/UX 사이트 G3 준비 상태 — 2026-10-07

**판정: 현재 로컬 후보의 현장 G3 보류.** 2026-10-07 16:41 KST에 기존 사이트 PC를 SSH로 읽기 전용 확인했다. 비교 후보는 로컬 `main` commit `43a823ac5c0b5aae176636a4e90df6ae61619115`다.

| 확인 항목 | 관찰 |
|---|---|
| Fleet·Vision·proxy 실행 이미지 | 세 컨테이너 모두 commit `5eb726c132719c9b911f76b4c908a92a87c7be36` 태그를 보고했다. 이 커밋은 비교 후보의 조상이다. |
| mDNS 발견 | Avahi 활성. 두 로봇의 IPv4 `_rosy._tcp` 광고가 확인됐다. |
| Fleet 내부 이름 해석 | 실행 컨테이너의 서비스 UID `10001`에서 두 광고의 `.local` 이름 모두 해석됐다. |

원본 요약은 `X:/DevTemp/projects/rosy-platform/2026-10-07--site-g3-readiness/site-readback.txt`에 두었다(SHA-256 `f2e05d6a8c465559cfca852eb1537d1e6fbe5fe7c5548dac716d00ce6eb5f947`). `docker ps`, `avahi-browse`, Fleet UID의 `getent`, `systemctl is-active`와 로컬 `git merge-base`만 사용했다. 사설 주소·장치 이름·인증값은 공개 기록에 넣지 않았다.

이 확인은 발견 경로와 이미지 태그에 한정된다. 광고의 건강 문구는 실제 로봇 상태 readback이 아니고, 이미지 태그는 현재 후보 화면이 사이트에서 렌더됐다는 근거가 아니다. 현재 후보가 설치·식별된 뒤 실제 화면과 로봇·카메라 상태를 읽고, 요청자가 [운영자 G3 작업 기록](../uiux-surfaces-2026-10-06/operator-walkthrough.md)을 수행해야 한다. 그 전까지 제품 전체 UI/UX는 **HOLD**다.
