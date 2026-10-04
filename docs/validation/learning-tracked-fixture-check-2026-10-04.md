# 추적된 테스트 fixture까지 포함한 저장소 검사

앞선 [guard 수정 기록](learning-integration-guard-repair-2026-10-04.md)의 99 passed는
새 테스트 파일을 git에 올리기 전 실행이었다. 이후 추적된 파일까지 포함한 검사에서
그 테스트의 `f-string` credential/PSK/QR 샘플 3개가 탐지됐다. 해당 실행은
17 passed, 1 failed이며 저장소 검사 통과로 보지 않는다.

그 결과를 확인하기 전에 수정 커밋 `6eae392c6`를 기록한 실행 순서 오류가 있었다.
main은 변경하지 않았다. 검사나 예외를 늘리지 않고 테스트 샘플만 실행 시 문자열
조립으로 바꿨다. 실제 planted 값과 탐지 assertions는 그대로다. 후속 검증과 커밋은
이 기록 및 비공개 실행 로그에서 구분한다.

실제로 추적된 새 테스트와 기존 release/robot 검사를 함께 재실행해 99 passed를
확인했다. 따라서 새 파일을 제외한 검사 통과와 추적 파일을 포함한 통과를 구별한다.
독립 재검증도 추적된 새 테스트를 포함해 102 passed였고, scanner 및 inventory는
변경하지 않았음을 확인했다. 앞선 독립 결과의 untracked 범위 한계도 명시했다.

비공개 실행 자료: `X:/DevTemp/rosy-learning-audit-20261004/merge-learning-guard-fix-v3`.
이 변경도 HOST 검사이며 장치 활성화나 전체 목표 완료 증거가 아니다.
