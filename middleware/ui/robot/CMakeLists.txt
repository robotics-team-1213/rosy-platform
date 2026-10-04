cmake_minimum_required(VERSION 3.8)
project(dashboard)

find_package(ament_cmake REQUIRED)

install(FILES
  index.html
  styles.css
  console-detail.css
  styleguide.html
  styleguide.css
  styleguide.js
  app.js
  entry-router.js
  dashboard-entry.js
  dashboard-entry.css
  telemetry.js
  teleop.js
  state-socket.js
  client.js
  dom.js
  host-cards.js
  map.js
  ros-network.js
  settings.js
  status-summary.js
  surface-navigation.js
  triage.js
  vision.js
  camera-capture.js
  DESTINATION share/${PROJECT_NAME}
)

install(FILES
  panels.yaml
  surface.html
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY
  shell
  panels
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
