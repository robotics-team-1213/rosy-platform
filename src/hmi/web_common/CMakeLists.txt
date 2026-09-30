cmake_minimum_required(VERSION 3.8)
project(web_common)

find_package(ament_cmake REQUIRED)

# shared-assets.json lists which of these files servers expose under /common/.
install(FILES
  shared-assets.json
  tokens.css
  components.css
  template.html
  core_ui_logic.js
  hold-ticker.js
  ui.js
  evidence.js
  DESTINATION share/${PROJECT_NAME}
)

# D-370 3항 surface icons, listed one by one in shared-assets.json (never the folder).
install(FILES
  icons/overhead-camera-app.svg
  icons/pilot.svg
  icons/fleet-console.svg
  icons/robot-dashboard.svg
  DESTINATION share/${PROJECT_NAME}/icons
)

ament_package()
