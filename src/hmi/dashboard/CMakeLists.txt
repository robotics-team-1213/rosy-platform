cmake_minimum_required(VERSION 3.8)
project(dashboard)

find_package(ament_cmake REQUIRED)

install(FILES
  index.html
  styles.css
  styleguide.html
  styleguide.css
  app.js
  client.js
  dom.js
  host-cards.js
  map.js
  ros-network.js
  settings.js
  triage.js
  vision.js
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
