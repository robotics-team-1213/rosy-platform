---
module: cam
tags: [android, apk, signing, pairing, site-camera]
problem_type: deployment
applies_when: installing a Rosy Cam APK built on a different PC than the installed one
---

# Rosy Cam 디버그 APK는 빌드한 PC마다 서명이 달라 재설치하면 연결이 지워진다

## 문제

2026-10-23 현장 천장 폰에 새로 빌드한 Rosy Cam을 올리려 했는데, 설치된 앱과 서명자가 달라
`install -r`이 되지 않았다. 앱을 지우고 설치하자 저장된 사이트 연결(호스트·토큰·CA pin)이 모두
사라져 천장 송출이 멈췄다.

## 원인

- 앱은 release 서명 없이 **디버그 키**로만 빌드된다. 디버그 키는 PC마다 `~/.android/debug.keystore`가
  따로 생성되므로, 다른 개발 PC에서 빌드한 APK는 서명자가 다르다. Android는 서명자가 다른 업데이트를
  거부하고, 지우면 DataStore·Keystore에 든 연결 정보도 함께 지운다.
- 앱은 minSdk 26이라 v2 서명만 있다. `keytool -printcert -jarfile`은 v1만 읽으므로 아무것도 출력하지
  않고, 서명이 "같아 보이는" 착각을 부른다.
- 이 현장은 콘솔 승인 페어링(`ROSY_SITE_PAIRING`)이 꺼진 `credential: static` 소스라, 폰에서
  「사이트에 연결 요청」을 보낼 수 없다. 재연결에는 고정 토큰이 든 `rosyov://` 링크가 필요하다.

## 해결과 복구

1. 빌드 **전에** 설치된 APK의 v2 서명자 SHA-256과 빌드 PC의 디버그 키 SHA-256을 비교한다. 설치본은
   `adb shell pm path <패키지>`로 받아 `apksigner verify --print-certs`로 읽는다(빌드 도구 35에 있다).
   같으면 `install -r`이 연결을 유지한다.
2. 다르면 원래 키가 있는 PC에서 빌드하거나, 송출 중단과 재연결을 감수하고 지운 뒤 설치한다.
3. static 소스 재연결: 링크를 사람 눈·채팅·로그에 내지 않고 Vision 컨테이너 안에서 만든다.
   `/run/secrets/phone_ingress_token`, `site_ca`(pin), `site_cert`(leaf+CA)로
   `rosy_vision.protocol.pairing_uri(..., secure=True, pin=cli._choose_ca_pin(site_cert, site_ca))`를 권한 077
   임시 파일에 쓰고, `adb shell am start -a android.intent.action.VIEW -d "<링크>" io.github.livsbittt.rosy.cam`으로
   넘긴 뒤 파일을 지운다. 앱의 「연결 정보를 바꿀까요?」에서 호스트·카메라 이름을 확인하고 저장한다.
4. `deploy/site/rosy_cam_screen.py stream-start`로 송출을 켜고 `snapshot`으로 확인한다.

## 검증 근거

설치본 v2 서명자와 현장 PC·노트북 디버그 키가 서로 달랐다(keytool은 설치본에서 빈 결과).
재설치 뒤 위 링크로 다시 연결해 앱 「송출 중」 2.5 fps와 `stream-status running: true`를 확인했다.

## 다음에 적용할 조건

Rosy Cam을 기기에 올리기 전, 특히 처음 쓰는 PC에서 빌드할 때. 콘솔 승인 페어링이 켜진 현장이면
3번 대신 콘솔 「카메라 연결 승인」으로 다시 연결한다.
