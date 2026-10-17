cmake_minimum_required(VERSION 3.16)
project(map_adoption_wire_check LANGUAGES CXX)

# Standalone verification fixture, not another ROS package or consumer owner.
find_package(ament_cmake REQUIRED)
find_package(interfaces REQUIRED)
find_package(rclcpp REQUIRED)
add_executable(map_adoption_wire_check wire.cpp)
target_compile_features(map_adoption_wire_check PRIVATE cxx_std_17)
ament_target_dependencies(map_adoption_wire_check interfaces rclcpp)
enable_testing()
add_test(NAME native_map_wire_cpp COMMAND map_adoption_wire_check)
