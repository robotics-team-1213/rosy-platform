# 사용자 직접 검수를 위한 영상 라벨 편집기

2026-10-04, 사용자 요청으로 별도 video_label_review 세션에서 구현하고 독립 검토했다.
검수자는 사용자이며 다른 세션의 시각 검토는 assistant 초안이다. 실제 정답 승인으로 대체하지 않는다.

## 실제 산출물과 인계

최종 사용 경로는 `X:/DevTemp/rosy-learning-audit-20261004/recorded-video-review-v2-verified/review.html`이다.
구 v2/v2-final 폴더는 QA 이력이며 사용자 검수본으로 안내하지 않는다.

객체 4프레임/7박스와 분할용 원본 76프레임을 확인한다. 객체는 클릭 선택,
드래그 추가·재그리기·삭제, 클래스·신호 상태와 JSON 편집을 지원한다.
신호 상태는 식별되지 않으면 unknown이며 작은 실제 신호등 초안은 unknown을 유지했다.
각 프레임의 전체 객체 확인 체크와 명시적 승인이 필요하고 편집 후에는 승인/완료를 해제한다.
사용자는 검수 후 human-review.jsonl을 저장해 반환한다.

자동 다운로드는 agent-browser에서 Download was canceled로 실패했다. 파일 다운로드 성공을
주장하지 않는다. 실제 브라우저에서 `현재 검수 JSONL 표시`의 4행을 확인했다.
다운로드가 막히면 표시한 내용을 복사해 UTF-8 human-review.jsonl로 저장한다.
새로고침·탭 종료 전에 저장해야 하며 편집은 메모리에만 남는다.

image SHA/index/source video/frame에 연결된 object-source.jsonl과 원본 객체 JPEG를 함께 보존한다.
첫 3객체 프레임은 320×240, 마지막은 640×480이다. 현재 object_boxes.py의 --size export는
크기별 입력/검수 행을 나누어 처리해야 한다. signal_state는 JSONL provenance로 보존하지만
YOLO txt 자체가 신호 상태 classifier를 학습시키는 것은 아니다.

벽·바닥·차선·drivable·정지선은 별도 CVAT 픽셀 마스크 검수이다.
`segmentation-human-review-v1`에 원본 76 JPEG의 images.zip, 동일 이름의 76마스크
draft-masks-cvat.zip, classes.yaml, frames.jsonl과 verification.json을 준비했다.
이미지·마스크 이름 일치를 확인했고 이미지 bytes/SHA 76개는 원본과 같다.
마스크 zip은 이전 초안 bytes 그대로이며 사람 승인 0이다. raw MP4 전체를 새로 hash한 것은 아니다.
이 편집기에서 segmentation을 수정하거나 승인하지 않는다. 실제 CVAT 업로드/검수도 수행하지 않았다.

## 검증

review_pack 테스트 6 pass, 독립 6 pass. 원본 80 이미지의 hash와 JPEG bytes,
4객체/7박스/76gallery/승인0, 복사 JSONL 4행의 index/hash 연결을 독립 확인했다.
source SHA-256: `578968a6dd3a006293b4ed00353c14a1f156fe7ce6846aa1e8bd50ae8a95b2e1`.
browser-initial.png, browser-copy-pending-output.json과 run.txt를 최종 pack에 보존했다.

실제 Chromium으로 확인한 사항: 승인 전 전체 검수 조건, 편집 후 승인 해제,
박스 추가·삭제, 프레임 이동, 현재 JSONL 표시와 기본 pending4.
독립 검토의 경로 재진입으로 출력 밖 쓰기 RED와 로딩 전 잘못된 이미지 승인 RED를 수정했다.
출력 경로를 제한하고 이미지 로딩 중 canvas/선택/승인·편집을 차단하며 token으로 지연 콜백을 구분한다.
최종 독립 검토는 이 두 수정과 원본 bytes 보존을 확인했다.

이는 검수 인계 도구와 SOURCE/HOST/브라우저 증거다. 사람 라벨 수용·새 데이터셋 학습,
클래스별 독립 평가·모델 PC·로봇 shadow/rollback·DEVICE/FIELD는 아직 완료되지 않았다.
