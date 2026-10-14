# OMX 준비 코드 공개와 CI 의존성 수정

2026-10-14. branch `fix/runtime-jose-lock`. 기기 배포·동작 수용 기록은 아니다.

## 공개 결과와 실패 재현

사용자가 승인한 공유 main의 `76a8361c5fa6e77a1395cda89f66536028225f60`을
원격 main에 push했다. pre-push 원격 시험은 네 invocation에서 각각
518, 8242, 6895, 6671 passed였고 알려진 실패 비교는 모두 NEW 0이었다.
Android unit 및 unsigned site candidate build는 성공했다. 후보 생성은 배포가 아니다.

[CI 38537795221](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38537795221)은
모든 시험 entry의 ROS-free wheel 설치에서 실패했다. `core_common`이 요구하는
`joserfc==1.7.5`가 없고 `--no-index --find-links wheelhouse`로 외부 다운로드도
막혀 있었다. 시험 실행 전 실패이므로 원격 pytest 통과와 별개다.

## 수정과 확인

`48eff5cc6`은 wheel 설치 전 dependency provider를 검사하는 회귀검사를 추가했다.
원격 RED는 해당 누락으로 1 failed, NEW 1이었다. `ff848d70c`는 기존 CI의
분리된 receiver crypto target에 `joserfc==1.7.5`를 `--no-deps`로 설치한다.
이미 있는 cryptography 50.0.0과 frozen device runtime lock은 변경하지 않는다.

`ff848d70c`의 원격 GREEN은 다음 네 파일에서 96 passed, exit 0, NEW 0이었다.

```text
test/test_ci_dependencies.py
test/test_python_runtime_id.py
contracts/foundation/test/test_account_client.py
test/test_image_customization_contract.py
```

독립 소스 검토에서 차단 결함은 발견되지 않았다. 위 시험은 회귀·런타임
식별자 계약 확인이다. 수정된 실제 CI wheel 설치와 전체 matrix의 성공 여부는
다음 push의 terminal CI에서 따로 확인해야 한다.
실제 Gazebo, 물리 OMX, Hugging Face upload/readback과 정책 수용은 이 기록에
포함되지 않는다. 실행 전제와 미정 입력은 D-756 및 OMX simulation 준비 계획을 따른다.
