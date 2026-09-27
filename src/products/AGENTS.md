# products

제품 전용 ROS 패키지와 구성을 제품별로 묶는다. `pinky_pro/profile`과 `omx/profile`은 각각 기존 `pinky_pro`, `omx` 설정 패키지이며 부모 제품 폴더는 ROS 패키지가 아니다. Pinky 보드 패키지는 `pinky_pro/{bringup,adc,lamp,led}`, OMX adapter는 `omx/adapter`에 있다. 폴더 위치는 최종 명령 제어권이나 이미지 설치 내용을 증명하지 않는다. CORE는 주행 최종 명령을 계속 소유하고 OMX adapter의 운영 허가는 별도 검증 대상이다.
