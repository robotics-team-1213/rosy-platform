#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <memory>
#include "rclcpp/rclcpp.hpp"
#include "hardware_interface/component_parser.hpp"
#include "dynamixel_hardware_interface/dynamixel_hardware_interface.hpp"
int main(int argc, char **argv) {
  if (argc != 2 || std::filesystem::exists("/nonexistent")) return 3;
  std::ifstream file(argv[1]); std::stringstream bytes; bytes << file.rdbuf();
  auto systems = hardware_interface::parse_control_resources_from_urdf(bytes.str());
  if (systems.size() != 1) return 4;
  systems[0].hardware_parameters["port_name"] = "/nonexistent/rosy_omx_negative_probe/serial";
  systems[0].hardware_parameters["disable_torque_at_init"] = "false";
  for (const auto &gpio : systems[0].gpios) {
    if (gpio.parameters.at("type") != "dxl" || gpio.parameters.at("Torque Enable") != "0" ||
        gpio.parameters.at("Reboot") != "0") return 5;
  }
  rclcpp::init(argc, argv);
  int code = 2;
  {
    auto executor = std::make_shared<rclcpp::executors::SingleThreadedExecutor>();
    hardware_interface::HardwareComponentInterfaceParams params;
    params.hardware_info = systems[0]; params.executor = executor;
    auto driver = std::make_shared<dynamixel_hardware_interface::DynamixelHardware>();
    std::cout << "ROS_DRIVER_CONSTRUCTED" << std::endl;
    auto result = driver->on_init(params);
    std::cout << "ON_INIT_RETURN=" << static_cast<int>(result) << std::endl;
    code = result == hardware_interface::CallbackReturn::ERROR ? 0 : 6;
    driver.reset();
    std::cout << "DRIVER_DESTRUCTED" << std::endl;
  }
  rclcpp::shutdown();
  return code;
}
