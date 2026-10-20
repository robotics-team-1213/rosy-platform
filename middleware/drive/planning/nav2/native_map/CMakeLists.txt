cmake_minimum_required(VERSION 3.16)
find_package(nav2_amcl 1.3.13 EXACT REQUIRED)
find_package(nav2_costmap_2d 1.3.13 EXACT REQUIRED)
find_package(rclcpp 28.1.22 EXACT REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(interfaces REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(pluginlib REQUIRED)
find_package(OpenSSL REQUIRED)

# Unsupported SDKs fail only the explicit native opt-in, never ordinary assets.
set(pin_file "${CMAKE_CURRENT_BINARY_DIR}/sdk-pins.txt")
file(WRITE "${pin_file}" "nav2=1.3.13;rclcpp=28.1.22\n")
function(check_sdk label header expected)
  find_file(SDK_${label} NAMES "${header}" HINTS ${ARGN})
  if(NOT SDK_${label})
    message(FATAL_ERROR "Native map SDK header missing: ${label}")
  endif()
  file(SHA256 "${SDK_${label}}" actual)
  if(NOT "${actual}" STREQUAL "${expected}")
    message(FATAL_ERROR "Unsupported native map SDK: ${label} ${actual}")
  endif()
  file(APPEND "${pin_file}" "${label}=${actual}\n")
endfunction()
get_target_property(costmap_sdk_includes nav2_costmap_2d::nav2_costmap_2d_core
  INTERFACE_INCLUDE_DIRECTORIES)
check_sdk(amcl nav2_amcl/amcl_node.hpp
  1afedba75bee4f1c0e9bc7a9a4d08d459b3304a3d402c747f5db731fc39fc348 ${nav2_amcl_INCLUDE_DIRS})
check_sdk(static nav2_costmap_2d/static_layer.hpp
  0cf2a51566af02c7f423b213dd4f73f4e5f1ee642042aa66f84050d5f0b68de5
  ${costmap_sdk_includes} ${nav2_costmap_2d_INCLUDE_DIRS})
check_sdk(costmap nav2_costmap_2d/costmap_2d_ros.hpp
  0c55e2a92389c188187628fa16f509febdb38f054d27d5527944d83e81b0572a
  ${costmap_sdk_includes} ${nav2_costmap_2d_INCLUDE_DIRS})
check_sdk(node rclcpp/node.hpp
  8c3d4a637f143b815c56bd389b70351e8c2c89a57d64a2df31f3c4d4cd15f33a ${rclcpp_INCLUDE_DIRS})
check_sdk(parameters rclcpp/node_interfaces/node_parameters_interface.hpp
  ce986454969419119b7e9a89d746655ed67d2008983087f5b4958657fb5c6703 ${rclcpp_INCLUDE_DIRS})
check_sdk(lifecycle rclcpp_lifecycle/lifecycle_node.hpp
  1fedfbcc5d0555eee474f94f342bfa8c53517a59f0021f98c274610a2c7f43b3 ${rclcpp_lifecycle_INCLUDE_DIRS})

get_filename_component(platform_root "${CMAKE_CURRENT_SOURCE_DIR}/../../../../.." ABSOLUTE)
file(READ "${pin_file}" fingerprint)
string(APPEND fingerprint
  "compiler=${CMAKE_CXX_COMPILER_ID}:${CMAKE_CXX_COMPILER_VERSION}\n"
  "flags=${CMAKE_CXX_FLAGS};${CMAKE_CXX_FLAGS_DEBUG};${CMAKE_CXX_FLAGS_RELEASE}\n"
  "build_type=${CMAKE_BUILD_TYPE};openssl=${OPENSSL_VERSION}\n")
file(GLOB_RECURSE native_sources CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/*.hpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/*.in" "${CMAKE_CURRENT_SOURCE_DIR}/CMakeLists.txt")
list(APPEND native_sources "${platform_root}/contracts/ros_idl/srv/MapAdoption.srv")
list(APPEND native_sources "${CMAKE_CURRENT_SOURCE_DIR}/../CMakeLists.txt"
  "${CMAKE_CURRENT_SOURCE_DIR}/../package.xml")
list(APPEND native_sources "${CMAKE_CURRENT_SOURCE_DIR}/native_plugins.xml")
list(SORT native_sources)
foreach(source IN LISTS native_sources)
  file(SHA256 "${source}" hash)
  file(RELATIVE_PATH name "${platform_root}" "${source}")
  string(APPEND fingerprint "${name}=${hash}\n")
endforeach()
string(SHA256 native_build_id "${fingerprint}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/build-fingerprint.txt" "${fingerprint}")
configure_file(build_id.hpp.in generated/rosy_native_map/build_id.hpp @ONLY)

add_library(rosy_native_map SHARED grid.cpp support.cpp amcl.cpp static_layer.cpp)
target_compile_features(rosy_native_map PUBLIC cxx_std_17)
target_include_directories(rosy_native_map PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
  $<INSTALL_INTERFACE:include>)
ament_target_dependencies(rosy_native_map nav2_amcl nav2_costmap_2d rclcpp
  rclcpp_lifecycle lifecycle_msgs interfaces nav_msgs pluginlib)
target_link_libraries(rosy_native_map OpenSSL::Crypto nav2_costmap_2d::layers)
add_executable(rosy_verified_amcl amcl_main.cpp)
target_link_libraries(rosy_verified_amcl rosy_native_map)
ament_target_dependencies(rosy_verified_amcl rclcpp nav2_amcl interfaces)
install(TARGETS rosy_native_map LIBRARY DESTINATION lib)
install(TARGETS rosy_verified_amcl RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)
install(FILES LICENSE.LGPL-2.1 LICENSE.BSD-3-Clause DESTINATION share/${PROJECT_NAME}/native_map)
install(FILES "${pin_file}" "${CMAKE_CURRENT_BINARY_DIR}/build-fingerprint.txt"
  DESTINATION share/${PROJECT_NAME}/native_map)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(native_map_grid ../test/native_map_grid/grid_test.cpp TIMEOUT 30)
  target_link_libraries(native_map_grid rosy_native_map)
  ament_target_dependencies(native_map_grid nav_msgs)
  ament_add_gtest(native_map_amcl ../test/native_map_amcl_test.cpp TIMEOUT 120)
  target_link_libraries(native_map_amcl rosy_native_map)
  ament_target_dependencies(native_map_amcl nav2_amcl rclcpp rclcpp_lifecycle interfaces lifecycle_msgs)
  find_package(nav2_msgs REQUIRED)
  find_package(tf2_ros REQUIRED)
  find_package(geometry_msgs REQUIRED)
  find_package(std_srvs REQUIRED)
  ament_add_gtest(native_map_static ../test/native_map_static_test.cpp TIMEOUT 180)
  target_link_libraries(native_map_static rosy_native_map nav2_costmap_2d::nav2_costmap_2d_core)
  ament_target_dependencies(native_map_static nav2_costmap_2d nav2_msgs tf2_ros geometry_msgs
    std_srvs rclcpp rclcpp_lifecycle interfaces lifecycle_msgs)
endif()
