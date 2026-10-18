# 원격 검증 미실행 기록

2026-10-17. [수정 기록](result.md)에 이어 최종 전달 커밋 `a1372f7e7`의 확인 상태를 기록한다.

기준 커밋의 다섯 node 재확인과 최종 전달 커밋의 브라우저 검증 모두 시험 PC를 찾지 못했다.
각각 도구의 30초 간격·최대 600초 재시도가 끝났고 runner exit는 1이다.
pytest 실패나 skip이 아니라 **시험 미실행**이다. 최종 커밋의 의도한 두 invocation에는
브라우저 opt-in이 있고, 보정 표시 node는 단독 실행하도록 분리했다.
초기 수정 커밋의 별도 대기는 최종 전달 커밋으로 대체하며 취소했다.

확인된 것은 JavaScript/Python 구문, 공백, 린트 오류 0건(기존 경고 33건),
전달 커밋의 크기·safety 검사, 독립 코드 검토다. 최종 diff의 다섯 실패 목록 항목은
기준과 바이트 단위로 같다. 실제 UI 배치·인증·정지·보정 표시 성공이나
브라우저 캡처를 확인했다는 뜻은 아니다.

원본 증거는 저장소 밖 `C:/DevTemp/browser-regressions/`에 있다.
`baseline-runner.txt`와 `delivery-focused-runner.txt`는 접속 실패와 종료 사유,
`delivery-focus-selection.json`은 최종 source SHA와 node 목록,
`delivery-affected.json`은 관련 변경 범위(mode affected, FULL 승격 없음)를 보존한다.
`resume.json`은 연결 복구 후 실행 순서다. 로컬 pytest 대체 실행은 하지 않았다.

이 후속 수정은 `fix/browser-regressions-ready`에 보존한다. 다섯 node의 실제 성공과
skip 없음·실패 비교를 확보하기 전에는 실패 항목을 해제하지 않는다. 필요한 회귀 검사
뒤에만 이 수정본을 main에 착지한다. 이전 카메라 교정 구현의 main 병합을 되돌린 것은 아니다.
이 시도에서는 main 착지·push·배포를 수행하지 않았다.
