# D-456 Native Cam LAN 승인 검토

독립 검토자 `/root/ship_fleet_cam_merge`: 최종 22 경로 SPEC·Quality·Safety SOURCE PASS.
검토 영수증 SHA256: `a4270018dc6fa07c78c1cbad65d11d2a0c6dfceea7e8c3fcbb13aa022d228548`.
실제 48개 XML의 해시와 합계를 확인해 JVM 366 PASS·fail/skip 0을 확인했다.
최종 marked-credential guard의 실제 assertion RED와 원본 복원 12 PASS를 읽었다.
이전 다섯 변이 검사는 rollback 수정 이전 소스의 363 PASS와 구분한다.

부모 소스는 후보 raw manifest를 확인한 뒤 CRLF/LF 정규화 비교로 22 경로 일치를
확인했다. Native/server 공개 golden JSON은 실제 바이트가 같으며 서명은 별도
Java→Python 교차 검증도 통과했다. 공개 nonce·서명은 정확한 경로/필드/값만
허용하며 다른 경로·다른 필드·변조값·추가 실제 자격·private PEM은 계속 검출한다.

Android Keystore P-256 신원과 별도 암호화 관계 저장소를 사용한다. 첫 접촉의
CA/leaf/hostname 확인 전 자격을 전송하지 않으며 승인 뒤 fresh proof로 영상
자격을 갱신한다. DataStore rollback은 관계 marker와 같은 값의 최신 선택을
보존한다. cam-peer 자격의 marker 누락은 legacy로 내려가지 않고 거부한다.
Stop/late renewal은 기존 생명주기와 세대 취소를 따르며 촬영을 자동 시작하지 않는다.

첫 화면은 같은 LAN의 수신 기기 목록과 기억한 연결을 보여준다. Bluetooth나
개발 설정 가져오기는 정상 접속의 전제가 아니다. 네 문자 값은 요청 대조용이고
현재 첫 CA 확인은 전체 지문 비교다. 실제 QR/SAS 네 문자 인증은 아직 활성화하지 않았다.

실제 Keystore·Android widget·동일 서명 앱 업데이트·서명 site 배포·두 화면 LAN
승인·DHCP/장기 오프라인 복귀·frame lease·발열 대응은 이 검토로 완료를 부여하지 않는다.
