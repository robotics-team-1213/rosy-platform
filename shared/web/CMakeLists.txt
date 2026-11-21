cmake_minimum_required(VERSION 3.8)
project(web_common)

find_package(ament_cmake REQUIRED)

# shared-assets.json lists which of these files servers expose under /common/.
install(FILES
  shared-assets.json
  tokens.css
  components.css
  stage-strip.css
  readout-strip.css
  template.html
  template.css
  app-shell.css
  core_ui_logic.js
  hold-ticker.js
  ui.js
  workspace.js
  confirmation.js
  live-dialog-geometry.js
  task-chooser.js
  ui-wiring.js
  task-chooser.css
  theme.js
  evidence.js
  webrtc.js
  request.js
  motor-health.js
  motor-health.css
  scope.js
  fleet-client.js
  account-profile.js
  account-apps.css
  account-session.js
  control-dom.js
  form-controls.js
  collection-controls.js
  interaction-controls.js
  workflow-controls.js
  robot-row.js
  robot-3d.js
  choice-logic.js
  robot-profile.js
  robot-dock.js
  robot-panel.js
  robot-3d-assets.js
  robot-3d-model.js
  evidence-line.js
  stop-control.js
  alert-center.js
  account-gate.js
  announcer.js
  busy-scope.js
  cause-line.js
  connection-notice.js
  choice-group.js
  choice-list.js
  selection.js
  status-tag.js
  value-text.js
  robot-dock-gallery.js
  robot-dock-model.js
  component-controls.css
  component-gallery.css
  component-gallery.html
  component-gallery.js
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

install(FILES
  brand/mark.svg
  brand/platform.svg
  DESTINATION share/${PROJECT_NAME}/brand
)

ament_package()
