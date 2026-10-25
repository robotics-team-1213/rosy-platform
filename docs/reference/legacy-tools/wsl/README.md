# 과거 WSL 동기화·진단 자료

D-637에서 현행 `tools`와 분리한 6개 스크립트의 원본이다. 예전 Rosy OS worktree와 `/rosy` 환경을 전제로 하며 현재 실행·배포 경로로 사용하지 않는다. 소스 복사·삭제·프로세스 종료 명령도 역사적 내용 그대로 보존한다.

2026-10-20 중복·배치 정리에서 일회성 카메라·브리지·시뮬 진단 스크립트 18개를 추가 보관했다. 고정 `/rosy` 작업 공간, PID 555, `/root/.ros/log` 또는 `/.ros/log`를 가정한 당시 원본이다. `restart_relay.sh`가 부르는 `/rosy/tools/start_relay_only.sh`도 당시 경로로 남겨 둔다. 현재 호출자가 있는 `tools/run_fleet_sim.sh`와 Pilot 런처는 현행 위치를 유지한다.

현재 검증은 `tools/remote/remote_pytest.py`, 시뮬레이션 호스트 선택은 그 도구의 `--pick sim`, 제품 설치는 `deploy/`의 해당 계약을 따른다. 이 자료를 새 폴더 경로로 바꿔 재사용하지 않는다.
