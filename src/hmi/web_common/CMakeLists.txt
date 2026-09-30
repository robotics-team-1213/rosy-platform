cmake_minimum_required(VERSION 3.8)
project(web_common)

find_package(ament_cmake REQUIRED)

# manifest.json lists which of these files servers expose under /common/.
install(FILES
  manifest.json
  tokens.css
  components.css
  template.html
  core_ui_logic.js
  hold-ticker.js
  ui.js
  evidence.js
  DESTINATION share/${PROJECT_NAME}
)

# D-370 3항 surface icons, listed one by one in manifest.json (never the folder).
install(FILES
  icons/cam.svg
  icons/pilot.svg
  icons/console.svg
  icons/robot.svg
  DESTINATION share/${PROJECT_NAME}/icons
)

ament_package()
