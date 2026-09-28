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
  input-state.js
  vision.js
  manifest.webmanifest
  sw.js
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY
  drivers
  screens
  icons
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
