cmake_minimum_required(VERSION 3.8)
project(pilot)

find_package(ament_cmake REQUIRED)

install(FILES
  index.html
  styles.css
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
