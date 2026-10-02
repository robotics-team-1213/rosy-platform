cmake_minimum_required(VERSION 3.8)
project(pilot)

find_package(ament_cmake REQUIRED)

install(FILES
  index.html
  styles.css
  stick.js
  link.js
  app.js
  client.js
  autonomy.js
  calibration.js
  recording.js
  controls.js
  arm-stick.js
  input-state.js
  vision.js
  manifest.webmanifest
  sw.js
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY
  drivers
  screens
  widgets
  icons
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
