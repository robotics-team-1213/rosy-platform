# OMX 후속 공개 범위와 계정 준비 검사

2026-10-15. branch `fix/omx-readiness-followup`. 물리 장치 수용 기록은 아니다.

## 확인과 수정

이전 공개 이후의 원격 main `8ba34d8e6`은 CI 38594387572에서 성공했다.
현재 미공개 main의 World 문서 변경은 canonical
`rosy.world.state.projections.map_pose`와 실제 Fleet 소비자에 맞는다.
독립 소스 검토에서도 차단 결함은 발견되지 않았다.

Fleet setup의 OAuthlib 3.3.1과 사이트·CI의 4.0.0 불일치를 정렬했다.
계정 SSO의 브라우저 시험은 일반 CORE 디렉터리 invocation에서 계속 opt-in으로
건너뛰고 있었다. full CI의 core-domain에 account_pipeline 파일 invocation을
별도 추가하고, 이 파일과 Fleet에만 Chromium 및 브라우저 옵션을 제공한다.
다른 CORE 브라우저는 활성화하지 않는다. 해당 파일의 일반 API 시험 하나는 중복된다.
선택적 PR 검사에서 이 파일이 포함되지 않는 경우는 full CI와 구분한다.

`82cdb320f`의 두 새 guard는 원격 RED 2 failed, NEW 2였다.
첫 연결의 함수 node id는 기존 file-path registry guard에서 거절됐다.
그 guard를 유지하고 파일 경로로 고친 `0349f6177`은 관련 원격
102 passed, 1 skipped, NEW 0, exit 0이었다. frozen device runtime 식별자도 확인했다.
아직 브라우저 시험 자체는 opt-in하지 않은 원격 검사이며, 실제 실행은 새 CI에서
별도로 확인해야 한다.

## live SIM 재개 조건

비현장 SIM headroom 확인은 모델 PC 20 CPU/3 GiB, AI PC 16 CPU/-9 GiB로
예약 반영 기준을 충족하지 못했다. 음수는 다른 작업 예약을 뺀 값이지 실제 RAM이 아니다.
모델 PC의 Docker daemon은 접근 거부였고 AI PC의 기본 PATH에서는 Docker/ROS/Gazebo
실행 파일을 찾지 못했다. PATH 확인은 ROS 설치 부재 판정이 아니다. 실제 이미지 목록은
확인하지 못했다. 권한·설치·다른 작업을 변경하지 않았다.
전용 builder, 사용 가능한 Docker context 및 SIM 8 CPU/8 GiB를 확보한 뒤 재개한다.

실물 PC·joint/camera 보정·HF 계정 선택·외부 upload/readback·Spaces 수용은
[D-756](../../adr/D-756-omx-imitation-preparation-and-resumption-gates.md)에 유지한다.
main 병합, push, 전체 CI 및 브라우저 결과는 이 원격 guard 검사와 별도 단계다.
