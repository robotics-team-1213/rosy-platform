# D-673 도로 관측 readback 일관성 재검증

기존 [고정 인지 재생 증거](fixed-road-fitness-replay-2026-10-12.md)의 후속 기록이다. D-659의 관측 전용 전달 중 파일 생성·readback 경계를 보완하며, 실제 장치 전달이나 독립 성능 수용을 주장하지 않는다.

## 수정과 원격 회귀

`1ef3bddb25`의 원격 RED는 올바른 새 파일 해시를 제시해도 snapshot 유효성·시각·calibration과 저장된 입력 오류가 모순되거나, 현재 구역이 임의의 도로 부분집합인 결과를 수용하던 문제를 재현했다. 추론 backend 예외가 진단 exit 2로 끝나지 않던 문제도 재현했다.

`7a03abf1af`는 공통 snapshot 검증, 기존 전처리 파서, D-670의 기준점 변환과 연결 구역 계산을 재사용한다. readback은 입력 오류 목록을 재계산하고 원본 기준점과 변환된 기준점·crop 범위·255·정확한 연결 구역과 보류 이유를 대조한다. 영상 오류 시 추론 보류, 기준점 오류 시 도로면 보존과 현재 구역 보류, 유한한 비음수 추론 지연을 확인한다. backend 실패는 보고서를 쓰기 전에 exit 2로 반환한다. 기존 exclusive 작성·hash 결속·grid 제한을 유지한다.

첫 GREEN에서 model revision 시험의 `invalid` 문자열은 기존 안전한 revision 토큰 계약상 유효해서 1건 실패했다. `f1255e01d2`에서 실제로 금지된 `../other` fixture로 교정했다. 최종 관련 원격 회귀는 103 passed / 3 skipped, terminal exit 0 및 known-failures NEW0이다. dependency 미설치 때문에 제외된 실제 추론 사례는 아래 별도 설치 환경에서 확인했다. 독립 소스 리뷰는 최종 수정에서 merge blocker를 발견하지 않았다.

## 실제 ONNX Runtime의 합성 실행

모델 PC의 기존 ML 환경에서 `f1255e01d2` archive의 SHA256을 검증한 후 실제 `rosy_ml observe`를 실행했다. 원본 12×12 합성 PNG, 6×6 예측 grid의 2:6 crop과 두 분리된 도로 구역을 생성하는 상수 ONNX를 사용했다. 도로면 16화소와 지정된 기준점에 연결된 현재 구역 8화소를 확인했다. 영상 무효 입력은 추론을 보류하고, 기준점 무효 입력은 도로면을 보존하며 현재 구역을 보류했다.

snapshot·구역·변환 기준점·crop·지연을 각각 모순되게 바꾸고 파일 SHA256을 다시 계산해도 다섯 사례 모두 readback이 거절했다. 실행 보고서를 내려받아 실제 SHA256을 재확인했다. ONNX 1.23.1, ONNX Runtime 1.26.0을 사용했다.

Source archive SHA256: `ef9552ff223201100bfb9191c3dccb0fb312c90d69586e2d8b1b76f8083a560c`.

Report SHA256: `ae9d300a0c417ea2d94b8f1c0959dfe82875c4705c24fe8bf76e54b422f1764b`.

비공개 X: 세션에 `synthetic-road-readback-proof-20261012.json`, `synthetic-road-readback-report-20261012.json`, `logs/road-readback-validity-{red,green-fixed}/run-1.txt`를 보존했다. 합성 영상·상수 모델은 실행 경로 증거이고 실제 카메라·사람 독립 정답·실물 또는 시뮬레이션 정확도 증거가 아니다. 판정은 HOLD다.

## 기존 검수 자료 추가 검색

모델 PC Desktop의 초기 drivable 검수본 1,428장을 새로 확인했다. 모든 행에 human_edit/done 기록이 있고 이미지 1,428개·마스크 1,428개의 실제 SHA256이 manifest와 일치했다. 그러나 기존 20261010 v2 2,769장에 이미지·마스크 해시 쌍이 전부 포함되어 추가되는 고유 정답은 0장이다. 초기본 설명은 흰 선을 넘지 않고 로봇에 연결된 바닥을 drivable로 정의하며 ignore_top은 110이다. 전체 도로면으로 재태깅하지 않는다.

구형 차선 자료의 승인 표시 857개도 확인했다. 그 클래스셋에는 drivable이 없고 일부 승인 표시는 사용자의 완료 선언에 따른 기존 needs_fix 정리이므로 새 픽셀 편집 이력으로 확대하지 않는다. 실제 평가 workspace의 225장과 8장은 모두 pending이다. training workspace의 프레임 승인 1건은 픽셀 마스크가 pending이며 독립 평가 승인이 아니다. 합성 시험의 승인 DB는 실제 검수 자료에서 제외했다.

세 PC의 관련 자료 폴더를 깊이 12로 재검색했으며 시간 제한에 도달하지 않았다. 일부 접근 오류와 제외된 코드·환경·cache·scratch·심볼릭 링크 때문에 외부 보관소 전체의 부재를 증명하지 않는다. 비공개 근거는 `existing-reviewed-data-followup-20261012.md`와 `older-review-*-r2-20261012.json`에 보존했다.

독립 전체 도로면·현재 구역 정답, 실제 upstream 학습 출처 closure, map_v2_fleet과 260919 MAP FILE.STL 계보를 유지한 독립 시뮬레이션 실행, 물리 기준점·보정, 사전 수용 profile, 실제 장치의 관측 전용 전달·버전 readback·capture-to-result 지연/손실은 미완료다. 이번 증거는 주행 활성화·배포·현장 수용을 승인하지 않는다.
