# D-427 원격 통합의 배포 로그 손상 감사 (2026-10-04)

입력: `075259a20`(원격 기준 `6a37dd732`)의 `deploy/logs.md`. `429e13b83134`에서 들어온 SIM AID 로그 항목 하나가 비가역적인 `?` 인코딩 손상으로 lint 오류 2건을 만들었다. 기술 설명과 실행 결과를 손상 문자열에서 복원하지 않는다.

원문의 정규화 블록 SHA256은 `e2f80dbdfc41bdcff21a27d50ddd7ae909a32d02270c5db525808c6d9977883d`, UNKNOWN 감사 치환 블록 SHA256은 `67eaec5a21a55c4caae24e613cc745fe16f6c6af0a6560a560d5807c600b1a92`이다. 원문은 위 Git 이력과 `X:/DevTemp/rosy-d427/resume/journal-429-audit/original-block.txt` 및 원래 전체 journal에 보존한다. 치환한 블록을 되돌려 비교했을 때 나머지 journal 바이트는 정확히 동일하다. 다른 peer 항목과 기존 인코딩 복구 pair는 유지한다.

기존 harness의 정확한 old/new SHA256 registry에 이 pair 하나만 추가했다. 제목과 문구의 느슨한 예외, 새 손상 허용, 검사 생략은 추가하지 않았다. 새 audit의 Change·Evidence·Gate는 모두 UNKNOWN이며 이 기록으로 SOURCE·LOCAL·ROS-SIM 또는 장치 수용을 승격하지 않는다.

실제 역사 블록을 Git에서 읽는 시험은 치환 전 `is_append_only=False`에서 RED였다(1 failed/7 passed, native EXIT1). 수정 뒤 해당 pair와 source/target 1문자 변조·치환 삭제·다른 peer 블록 삭제/변조·유사한 미래 손상 거부를 함께 검증했다. 새 corruption 탐지도 그대로 작동한다. 문서 배치·folder layout·network topology·harness·publication·감사 시험의 합계는 실제 111 passed/1 skipped, 51.32초, known_failures NEW 0이다. 별도 lint는 오류 0건·freshness 경고 21건이다. 이 시험의 skip과 경고를 장치 통과로 간주하지 않는다.

원본 및 후속 로그: `named-proof-checks/lint.txt`(첫 원격 기준 실패), `journal-429-audit/baseline-red.txt`, `journal-429-audit/baseline-red-result.json`, `named-proof-checks-journal-public-ref-final/{lint.txt,focused.txt,known-failures.txt,result.json}`. 공개 기록에는 실제 주소·계정·키를 넣지 않았다. G2의 실제 실행·총 시나리오 결과는 해당 담당자의 독립 증거가 필요하다.
