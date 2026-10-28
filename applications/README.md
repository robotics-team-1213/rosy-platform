# ROSY Applications

공개 ROSY Platform 저장소 안에서 제품 앱을 나누어 개발하는 위치다. 현재 앱은 [Fleet](fleet/README.md)이다.

앱별 화면·실행 조합·설정 예시·테스트·실행 안내는 `applications/<product>/`에 둔다. 플랫폼의 장치 기능은 `middleware/`, 현장 API·관측·작업 조정은 `operations/`, 공통 규격은 `contracts/`에서 관리한다. 공통 web 자산은 `shared/web/`을 사용한다.

새 앱은 자기 실행 방법과 사용하는 API·플랫폼 의존성을 README에 기록한다. 독립 서버나 프런트엔드 빌드 도구는 실제 필요할 때만 추가한다. 협업 브랜치와 검증 절차는 [개발 안내](../docs/reference/developer-guide.md)와 [Git 작업 안내](../docs/reference/git-workflow.md)를 따른다.
