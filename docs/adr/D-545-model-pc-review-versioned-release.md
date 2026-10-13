## D-545 모델 PC 검수 앱의 버전별 코드 릴리스

**Status:** Accepted (2026-10-09, 사용자 지시. 모델 PC 적용과 화면 확인은 별도 증거로 기록한다.)

## 배경

모델 PC의 `rosy-review-v13.service`는 Git 저장소가 아닌 복사된 코드 폴더의 `review_app.py`를 직접 실행했다. 검수 스튜디오 UI를 그 폴더에 수동 반영했지만 다음 전체 코드 배포가 같은 폴더를 교체하면 화면이 사라질 수 있다. 검수 DB는 이미 별도의 `review-v13-drivable/state`에 있다.

## 결정

1. 검수 앱의 실행 코드는 `review-v13-code/releases/<release-id>`에 불변으로 보존하고, 서비스는 `review-v13-code/current` 심볼릭 링크만 참조한다. 기존 런타임 폴더는 첫 전환의 입력으로만 사용한다.
2. 입력은 `review_app.py`, 웹 자산, 공유 웹 자산 및 Python import를 모두 포함한 **완전한 실행 소스**다. 소스 해시와 릴리스 이름을 기록한다. 상태 DB·영상·가중치·비밀은 릴리스에 포함하지 않는다. 상태 경로는 지금의 별도 경로로 유지한다.
3. 전환 전 필수 파일·경로 분리·복사 해시·Python import를 확인한다. 링크와 사용자 서비스 유닛을 바꾸고 서비스를 재시작한 뒤 `GET /api/workspace`, `GET /pixels`를 확인한다. 실패하면 기존 링크와 서비스 유닛을 복구하고 이전 서비스를 다시 시작한다. 이전 릴리스는 남겨 명시적으로 재활성화할 수 있게 한다.
4. 소스 업로드는 고정된 검증 커밋 또는 현재 실제 실행 코드의 복사본에서만 한다. 저장소 `main`의 변경이 모델 PC에 자동 배포되었다고 간주하지 않는다. 검수 앱 코드 릴리스는 검수 승인, 학습 모델 승격, 로봇 운행 권한과 별개다.

## 검증 경계

설치기의 상태 보존·롤백은 호스트 테스트와 모델 PC 서비스 readback으로 확인한다. HTTP 응답은 화면 제공 여부만 증명한다. 실제 검수 저장·승인과 학습 데이터 반영, 사람의 라벨 수용은 각각 별도 확인한다.

**Related:** [D-459](D-459-pinky-persistent-label-review-application.md), [D-530](D-530-host-management-desired-state-and-guard.md), [D-532](D-532-v13-drivable-model-lineage.md), [D-538](D-538-review-studio-workflow.md).
