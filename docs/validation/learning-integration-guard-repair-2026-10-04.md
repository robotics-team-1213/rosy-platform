# 학습 통합 후보의 공개 provenance 검사

통합 후보 `ad967cd92`의 fast 검사는 460 passed, 2 failed, 2 skipped였다.
실패는 공개 학습 provenance digest의 entropy 오탐과 새 공통 계약의 Pinky
식별자 미분류였다. 두 검사는 별도 main 조회에서 모두 통과했으므로 학습 브랜치의
통합 문제로 처리했다. 기존 실패 목록에는 추가하지 않았다.

검토된 공개 provenance 87행은 파일 경로·정확한 UTF-8 문장의 SHA256·해시 token으로
묶었다. 독립 검토자는 모든 행과 문맥을 읽고 공개 model/dataset/source 식별자임을
확인했으며 실제 행과 token 및 문장 SHA를 대조했다. 동결된 문서와 로그는 보존했다.

저장소 검사에서만 명시적으로 inventory를 읽는다. 정확한 tuple이 맞을 때 entropy
matcher의 해당 token만 허용한다. raw scanner·이미지 검사의 기본 동작과
credential·private key·Wi-Fi PSK·QR 검사는 그대로다. 문장 변경, 경로 변경,
같은 행/새 행의 추가 token, 허용된 문장에 들어간 credential 등은 여전히 검출된다.
잘못된 schema·경로·해시·중복·빈 검토 사유는 거절한다. 실제 inventory의 각 행이
현재 파일에 남아 있는지도 검사한다.

Pinky 식별자 두 파일은 D-449의 Episode/PolicyArtifact profile·owner·원본 schema
binding으로 분류했다. robot-literal backlog에 소유 사유를 명시했고 집합 일치
검사는 유지했다. 제품 profile 등록표가 승인되면 그 소유 경계를 정리해야 한다.

검증 결과:

- 신규 회귀 RED: loader가 없어서 import 실패. 최초 구현 후 15 passed.
- 실제 inventory·기존 release/robot 검사: 99 passed.
- 나머지 affected 검사: 717 passed, 59 skipped, 출력 인코딩 경고 1개.
  CLI child는 UTF-8을 출력하지만 Windows reader가 cp949로 읽던 문제였다.
  reader encoding을 UTF-8로 명시하고 thread 경고를 오류로 올려 재실행: 12 passed.
- 실제 관리자 설치는 다시 조회해 service/timer not-found·inactive임을 확인했다.
  설치 요청 후보 SHA도 기존 검토본과 일치했다.
- 수정 코드 독립 리뷰: APPROVE, guard 102 passed 및 CLI 12 passed.
  승인한 87 tuple과 실제 inventory 일치, inventory 자체 raw scan도 finding 0을 확인했다.

이 결과는 HOST 통합 증거다. 원격 CI, Linux의 skip 항목, 상시 서비스 설치,
사람의 정답 라벨, 로봇 shadow/rollback과 인증된 owner/Fleet 결과는 별도 수용이다.
전체 목표는 진행 중이며 main 착지·푸시·장치 활성화는 이 기록의 실행 결과가 아니다.

비공개 원본 증거: `X:/DevTemp/rosy-learning-audit-20261004/merge-learning-*.txt`.
