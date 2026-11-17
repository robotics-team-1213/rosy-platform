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
  geometry.js
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
  stop-control.js
  account-gate.js
  connection-notice.js
  announcer.js
  alert-center.js
  alert-center.css
  status-tag.js
  skill-state.js
  evidence-line.js
  sample-data.js
  robot-profile.js
  robot-row.js
  robot-dock.js
  robot-dock-model.js
  robot-dock-gallery.js
  robot-panel.js
  choice-list.js
  choice-group.js
  choice-logic.js
  robot-options.js
  selection.js
  choice-controls.css
  robot-dock.css
  robot-3d.js
  robot-3d-assets.js
  robot-3d-model.js
  site-twin-3d.js
  busy-scope.js
  cause-line.js
  value-text.js
  localization-state.js
  workflow-controls.js
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

# C15 3D view: vendored three.js (MIT) and the generated web meshes (tools/robot_meshes.py), listed one by one.
install(FILES
  vendor/three.module.min.js
  vendor/three.core.min.js
  DESTINATION share/${PROJECT_NAME}/vendor
)

install(FILES
  meshes/omx-f.urdf
  meshes/omx-link0.stl
  meshes/omx-link1.stl
  meshes/omx-link2.stl
  meshes/omx-link3.stl
  meshes/omx-link4.stl
  meshes/omx-link5.stl
  meshes/omx-link6.stl
  meshes/omx-link7.stl
  meshes/pinky-body.stl
  meshes/pinky-pro.urdf
  meshes/pinky-wheel.stl
  DESTINATION share/${PROJECT_NAME}/meshes
)

ament_package()
