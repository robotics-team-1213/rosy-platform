# D-442 U1 커밋 뒤 재검증

[첫 회귀와 독립 리뷰](manual-ownership-review-2026-10-04.md)의 제품 코드 커밋은 `7e53784a9`다.

커밋한 checkout에서 신규 소유권 시험과 문서 배치·폴더·secret-scan 시험을 함께 돌렸을 때 swarm 요청 하나가 200이었다. 동시에 진행한 마이그레이션 게이트의 부하 때문에 요청 처리 전에 실제 500 ms watchdog이 만료됐다. 활성 세션이라는 시험 전제가 끝났으며, 만료된 MANUAL을 허용하는 제품 규칙과 맞는 결과다.

HTTP admission 시험 두 곳만 시험용 watchdog을 60 s로 두어 활성 조건을 유지했다. 제품의 500 ms 기본값과 실제 만료를 확인하는 별도 회귀 시험은 유지한다. 제품 코드는 첫 리뷰 이후 바뀌지 않았다.

```text
python -m pytest middleware/core/gateway/test/test_manual_navigation_ownership.py
  test/architecture/test_document_placement.py
  test/architecture/test_folder_layout.py
  deploy/robot/pinky_pro/release/test/test_secret_scan.py -q
29 passed, 1 skipped in 9.17s
```

원시 결과: `X:\DevTemp\rosy-d427\resume\manual-committed-2.txt`. 호스트 재검증이며 ROS-SIM·ARM64·장치·실주행 수용은 NOT_RUN이다.
