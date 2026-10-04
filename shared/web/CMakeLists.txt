cmake_minimum_required(VERSION 3.8)
project(web_common)

find_package(ament_cmake REQUIRED)

# shared-assets.json lists which of these files servers expose under /common/.
install(FILES
  shared-assets.json
  tokens.css
  components.css
  template.html
  template.css
  core_ui_logic.js
  hold-ticker.js
  ui.js
  workspace.js
  confirmation.js
  live-dialog-geometry.js
  task-chooser.js
  task-chooser.css
  theme.js
  evidence.js
  request.js
  scope.js
  fleet-client.js
  DESTINATION share/${PROJECT_NAME}
)

# D-370 3항 surface icons, listed one by one in shared-assets.json (never the folder).
install(FILES
  icons/cam.svg
  icons/pilot.svg
  icons/console.svg
  icons/robot.svg
  DESTINATION share/${PROJECT_NAME}/icons
)

ament_package()
