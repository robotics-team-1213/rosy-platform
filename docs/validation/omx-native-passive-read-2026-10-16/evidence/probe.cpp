#include <chrono>
#include <cmath>
#include <filesystem>
#include <dlfcn.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <sstream>
#include <thread>
#include <vector>
#include <unistd.h>
#include "dynamixel_interfaces/msg/dynamixel_state.hpp"
#include "rclcpp/rclcpp.hpp"
#include "hardware_interface/component_parser.hpp"
#include "dynamixel_hardware_interface/dynamixel_hardware_interface.hpp"
int main(int argc, char **argv) {
  const bool description_only = argc == 4 && std::string(argv[3]) == "--description-only";
  if (argc != 3 && !description_only) return 3;
  const std::string port(argv[2]);
  if (!description_only && (port.rfind("/dev/serial/by-id/", 0) != 0 || !std::filesystem::is_character_file(port))) return 4;
  using GuardActive = int (*)(const char *);
  auto guard = reinterpret_cast<GuardActive>(dlsym(RTLD_DEFAULT, "rosy_omx_probe_guard_active"));
  if (!description_only && (!guard || !guard(port.c_str()))) return 14;
  std::ifstream file(argv[1]); std::stringstream bytes; bytes << file.rdbuf();
  auto systems = hardware_interface::parse_control_resources_from_urdf(bytes.str());
  if (systems.size() != 1 || systems[0].gpios.size() != 6) return 5;
  const std::set<std::string> allowed{"ID", "type", "Torque Enable", "Reboot"};
  int id = 11;
  for (const auto &gpio : systems[0].gpios) {
    if (gpio.parameters.size() != allowed.size() || gpio.parameters.at("ID") != std::to_string(id++) ||
        gpio.parameters.at("type") != "dxl" || gpio.parameters.at("Torque Enable") != "0" ||
        gpio.parameters.at("Reboot") != "0") return 6;
    for (const auto &param : gpio.parameters) if (!allowed.count(param.first)) return 7;
  }
  if (description_only) { std::cout << "DESCRIPTION_ONLY_VALIDATED" << std::endl; return 0; }
  systems[0].hardware_parameters["port_name"] = port;
  systems[0].hardware_parameters["disable_torque_at_init"] = "false";
  const std::string topic = "/omx_passive_probe_" + std::to_string(getpid()) + "/dxl_state";
  systems[0].hardware_parameters["dynamixel_state_pub_msg_name"] = topic;
  rclcpp::init(argc, argv);
  auto observer = std::make_shared<rclcpp::Node>("omx_passive_probe_observer");
  int64_t last_stamp_ns = 0, read_started_ns = 0;
  size_t confirmations = 0;
  auto subscription = observer->create_subscription<dynamixel_interfaces::msg::DynamixelState>(
    topic, rclcpp::SystemDefaultsQoS(), [&](const dynamixel_interfaces::msg::DynamixelState::SharedPtr msg) {
      int64_t stamp = static_cast<int64_t>(msg->header.stamp.sec) * 1'000'000'000 + msg->header.stamp.nanosec;
      int64_t now = rclcpp::Clock(RCL_SYSTEM_TIME).now().nanoseconds();
      if (msg->comm_state != 0 || msg->id.size() != 6 || msg->torque_state.size() != 6 ||
          msg->dxl_hw_state.size() != 6 || stamp <= last_stamp_ns || stamp < read_started_ns ||
          stamp > now || now - stamp > 250'000'000) return;
      for (size_t i = 0; i < 6; ++i) {
        if (msg->id[i] != static_cast<int>(11 + i) || msg->torque_state[i] || msg->dxl_hw_state[i]) return;
      }
      last_stamp_ns = stamp; ++confirmations;
    });
  int code = 0;
  {
    auto executor = std::make_shared<rclcpp::executors::SingleThreadedExecutor>();
    hardware_interface::HardwareComponentInterfaceParams params;
    params.hardware_info = systems[0]; params.executor = executor;
    auto driver = std::make_shared<dynamixel_hardware_interface::DynamixelHardware>();
    auto result = driver->on_init(params);
    std::cout << "PASSIVE_ON_INIT=" << static_cast<int>(result) << std::endl;
    if (result != hardware_interface::CallbackReturn::SUCCESS) code = 8;
    else {
      auto interfaces = driver->export_state_interfaces();
      const std::vector<std::string> names{"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"};
      std::vector<hardware_interface::StateInterface*> joints;
      for (const auto &name : names) {
        hardware_interface::StateInterface *found = nullptr;
        for (auto &item : interfaces) {
          if (item.get_prefix_name() == name && item.get_interface_name() == "position") {
            if (found) { code = 9; break; }
            found = &item;
          }
        }
        if (!found) { code = 9; break; }
        joints.push_back(found);
      }
      auto discovery_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
      while (subscription->get_publisher_count() != 1 && std::chrono::steady_clock::now() < discovery_deadline) {
        rclcpp::spin_some(observer); std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
      if (subscription->get_publisher_count() != 1) code = 12;
      for (int sample = 0; code == 0 && sample < 3; ++sample) {
        size_t before = confirmations;
        read_started_ns = rclcpp::Clock(RCL_SYSTEM_TIME).now().nanoseconds();
        if (driver->read(rclcpp::Clock(RCL_SYSTEM_TIME).now(), rclcpp::Duration::from_seconds(.1)) != hardware_interface::return_type::OK) {
          code = 10; break;
        }
        auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(250);
        while (confirmations == before && std::chrono::steady_clock::now() < deadline) {
          rclcpp::spin_some(observer); std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        if (confirmations != before + 1) { code = 13; break; }
        std::ostringstream line; line << std::setprecision(17) << "NATIVE_SAMPLE " << sample << " " << last_stamp_ns << " [";
        for (size_t i = 0; i < joints.size(); ++i) {
          auto value = joints[i]->get_optional<double>();
          if (!value || !std::isfinite(*value)) { code = 11; break; }
          line << (i ? "," : "") << *value;
        }
        if (code == 0) std::cout << line.str() << "]" << std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
    }
    driver.reset();
    std::cout << "PASSIVE_DRIVER_DESTRUCTED" << std::endl;
  }
  rclcpp::shutdown();
  return code;
}
