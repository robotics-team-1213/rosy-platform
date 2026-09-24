cmake_minimum_required(VERSION 3.8)
project(web_common)

find_package(ament_cmake REQUIRED)

install(FILES
  tokens.css
  components.css
  core_ui_logic.js
  ui.js
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
