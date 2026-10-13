# 지도 종류와 기본 정보 관리 검증 — 2026-10-11

계약: [D-635](../../adr/D-635-map-profile-purpose.md). 브랜치 `fix/fleet-map-pose-stability`.

## 구현

- 프로필마다 lane_course / soccer / general 종류, 설명, soccer 경기장 길이·폭·골대 폭(m)를 보관한다. 기존 지도·ID·revision·권한·감사를 유지한다.
- 기존 SQLite 테이블에는 기본 정보 JSON 열만 추가한다. 기존 행과 이전 클라이언트의 기본 정보 생략 요청을 보존한다. metadata 변경도 revision 비교 대상이다.
- 축구장 템플릿은 입력 치수의 중심 원점 경계 점을 생성한다. 차로를 만들지 않는다. 같은 경계 점이 있는 저장 프로필만 축구 기준선을 그린다. 임의 지도에 경기장 선을 덮어 맞는 것처럼 보이지 않는다.
- 종류·설명·치수 저장, 재선택, 프로필 JSON 파일 불러오기, 데스크톱·모바일 표시를 지원한다. 프로필 선택·저장은 활성 지도를 변경하지 않는다.
- Games의 Field / SoccerGame / Observation과 경기 설정은 source에서 확인했다. Games 실행·Vision 축구 인식·실측 좌표 변환에 기본 정보를 자동 적용하는 경로는 아직 구현하지 않았다.

## 검증

| 커밋 | 검증 | 결과 |
|---|---|---|
| a6cdea941 | 기존 API/DB 기본 정보 미지원 재현 | 기대한 신규 시험 2개 실패, 이후 수정 |
| cd0231d7b | 관련 원격 pytest: map profiles, site-map API, server app, harness contracts | 175 passed, NEW 0 |
| cd0231d7b | 전체 Console Node 계약 | 285 passed |
| 3c46c775c | 실제 Chromium: 축구장 정보·경계 템플릿·파일, 기존 프로필·초안 분리, 각 1440/390px | 4 passed, NEW 0 |
| 655093d8a | 저장/갱신/구클라이언트 보존/DB 재개방과 입력 거부 | 11 passed, NEW 0 |

Browser 첫 실행은 새 시험의 파일 MIME 지정 누락으로 실패했다. 파일 payload에 application/json을 명시하고 같은 시나리오를 다시 검증했다. 초기 관련 pytest runner는 여유 자원 기준 미달 경고 뒤 원격 실행했고 exit 0이었다. 최종 Chromium과 persistence 실행은 자원 기준을 통과한 모델 PC에서 완료했다. 노트북 pytest는 실행하지 않았다.

로그: `X:/DevTemp/projects/rosy-platform/2026-10-11--132845--fleet-map-stability--65ca1e/logs/`의 profile-info-green, profile-info-browser-2, profile-info-persistence와 profile-info-node.txt. harness lint 오류 0·기존 모듈 증거 경고 25개.

## 한계

소스·원격 계약·브라우저 검증이다. main 착지·push·배포, 실측 경기장 교정, 로봇 축구 경기, Vision의 유형별 검출 정확도 수용은 확인하지 않았다. 예시 치수는 현장 측정치가 아니며 경기장 프로필만으로 게임이 시작되지 않는다.
