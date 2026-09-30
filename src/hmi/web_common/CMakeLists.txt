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

ament_package()
