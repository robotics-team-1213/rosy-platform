# R의 손 덮어쓰기 이미지를 서명 후보로 되돌리기

2026-11-13 R(`rosy-fleet-r`)은 운영 태그를 손으로 덮은 overlay 이미지로 돌았다: `rosy-site-fleet:authgap2-20261113`, `rosy-site-fleet:sitepose-20261113`, `rosy-site-vision:sitepose-20261113`. 운영 태그의 원본은 `rosy-site-fleet:pre-authgap-20261113`이다. 경위는 `Rosy/docs/workspace-records/2026-11-13/pinky-fleet-update-and-r-authgap.md`. 인증 공백 자체는 이제 `test/architecture/test_fleet_route_guards.py`가 main에서 막는다.

overlay는 임시다. 정본 경로는 [D-868](../adr/D-868-local-main-first-merge-commit-publish.md) 그대로다: 로컬 `main`에 착지하고, 공개 `main`에 merge commit PR로 올리고, CI와 서명 PC가 후보에 서명하고, 사이트 자동 갱신이 설치한다([D-301](../adr/D-301-site-candidate-signatures.md), [D-441](../adr/D-441-site-stack-automatic-update.md)). 서명 후보를 지나지 않는 이미지를 정본으로 두지 않는다.

## 되돌리는 순서

1. overlay가 담은 수정(인증 가드, `sitepose`)이 로컬 `main`에 들어갔는지 확인한다. 안 들어갔으면 먼저 착지한다. 그렇지 않으면 되돌리는 순간 수정이 사라진다.
2. 로컬 `main`을 공개 `main`에 올린다(`publish/main-*` PR, merge commit, squash 금지). 안전 태그 경로가 있으면 D-430 Safety-Review가 필요하다.
3. 서명 PC의 `audit.jsonl` 마지막 decision으로 서명을 확인한다. 릴리스 제목의 "(unsigned)"는 믿지 않는다(`release.json.sig` 자산이 정본, [진단 순서](../solutions/deployment/site-chain-stoppage-diagnose-from-audit-and-hold-not-release-titles-2026-11-03.md)).
4. R에서 `python3 deploy/site/rosy_site_autoupdate.py status`로 hold·failed를 본다. hold면 `resume`, 실패한 태그면 `forget-failed`. 서명 후보는 `sudo systemctl restart rosy-site-stack.service` 없이 자동 갱신이 설치하게 둔다.
5. overlay 태그는 후보가 설치된 뒤에 지운다. 설치 전에 지우면 되돌릴 이미지가 없다. 오버레이 이미지를 다시 빌드할 때도 마지막 `USER root`를 유지한다([핫패치 교훈](../solutions/deployment/site-stack-hotpatch-preserves-root-entrypoint-and-stateful-cell-handoff-2026-11-12.md)).

설치가 실패하면 자동 갱신의 롤백 기록이 이전 이미지를 되살린다. 그것도 안 되면 `docker tag rosy-site-fleet:pre-authgap-20261113 <운영 태그>` 뒤 스택을 재시작한다(Vision은 `rosy-site-vision:pre-sitepose-20261113`).

## 설치 뒤 확인

- 컨테이너가 실행하는 이미지가 서명 후보의 태그·ID와 같다: `docker image inspect`의 ID가 Fleet overlay ID(`4d6efe7f5bea`)와 다르다.
- Fleet·Vision이 healthy이고 `rosy-site-stack.service`가 active다.
- 로그인 없이 `GET /api/fleet/robots/<id>/road-nav2/plan`과 이동 경로 POST(`mode`, `berth-park`, `bay-departure`)가 401이다.
- 로그인 세션에서 관제 화면의 이동·berth-park가 동작한다(overlay 때 미확인이던 부분).
- 기체의 hub 연결이 online으로 돌아온다(`hub_online`, 스택 재시작 뒤 재연결).
- overlay가 바꾼 동작이 서명 후보에도 있다: 로봇 HTTP 오류 502, 팔 `execute`의 `executed: false`.
