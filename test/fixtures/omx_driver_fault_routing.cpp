// Native ROS consumer probe. Insert the actual pinned, patched vendor methods.
// Communication, status, torque-request and kinematic helpers are doubled.
// HardwareComponent is the actual installed ROS consumer.
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>
#include "hardware_interface/hardware_component.hpp"
#include "hardware_interface/system_interface.hpp"
#include "hardware_interface/types/hardware_component_params.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "rclcpp/rclcpp.hpp"
enum class DxlError { OK, ITEM_WRITE_FAIL, SYNC_WRITE_FAIL };
enum Status { DXL_OK, HW_ERROR, COMM_ERROR, REBOOTING };
struct Counts {
  int buffers = 0, goals = 0, disables = 0;
  int failed_disable_group = 0;
  DxlError buffer_result = DxlError::OK, goal_result = DxlError::OK;
};
struct Comm {
  Counts & counts;
  DxlError WriteItemBuf() { ++counts.buffers; return counts.buffer_result; }
  DxlError WriteMultiDxlData() { ++counts.goals; return counts.goal_result; }
  DxlError DynamixelDisable(const std::vector<int> & group) {
    ++counts.disables;
    return group.at(0) == counts.failed_disable_group ? DxlError::ITEM_WRITE_FAIL : DxlError::OK;
  }
};
struct DynamixelHardware : hardware_interface::SystemInterface {
  Comm comm;
  Comm * dxl_comm_;
  DxlError dxl_comm_err_ = DxlError::OK;
  Status dxl_status_ = DXL_OK;
  bool is_write_in_error_ = false;
  rclcpp::Duration write_error_duration_{0, 0};
  std::vector<int> dxl_comm_id_id_{11}, virtual_dxl_comm_id_id_{12};
  rclcpp::Logger logger_ = rclcpp::get_logger("omx_fault_routing_double");
  explicit DynamixelHardware(Counts & counts) : comm{counts}, dxl_comm_(&comm) {}
  DxlError CheckError(DxlError result) {
    dxl_status_ = result == DxlError::OK ? DXL_OK : COMM_ERROR; return result;
  }
  void ChangeDxlTorqueState() {}
  void CalcJointToTransmission() {}
  hardware_interface::CallbackReturn stop();
  hardware_interface::CallbackReturn on_error(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_shutdown(const rclcpp_lifecycle::State &) override;
  hardware_interface::return_type read(const rclcpp::Time &, const rclcpp::Duration &) override {
    return hardware_interface::return_type::ERROR;  // This probe supplies no sensor data.
  }
  hardware_interface::return_type write(const rclcpp::Time &, const rclcpp::Duration &) override;
};
// VENDOR_METHODS
static void require(bool value, const char * message) {
  if (!value) throw std::runtime_error(message);
}
int main(int argc, char **argv) try {
  rclcpp::init(argc, argv);
  auto executor = std::make_shared<rclcpp::executors::SingleThreadedExecutor>();
  auto clock = std::make_shared<rclcpp::Clock>(RCL_SYSTEM_TIME);
  using State = lifecycle_msgs::msg::State;
  using Result = hardware_interface::return_type;
  int cases = 0;
  for (int failure : {1, 2, 3, 0}) {
    for (int failed_group : {0, 11, 12}) {
      Counts counts; counts.failed_disable_group = failed_group;
      auto driver = std::make_unique<DynamixelHardware>(counts);
      auto * raw = driver.get();
      hardware_interface::HardwareComponent component(std::move(driver));
      hardware_interface::HardwareComponentParams params;
      params.hardware_info.name = "omx_fault_routing_" + std::to_string(cases);
      params.hardware_info.type = "system"; params.hardware_info.rw_rate = 100;
      params.executor = executor; params.clock = clock;
      require(component.initialize(params).id() == State::PRIMARY_STATE_UNCONFIGURED, "init");
      require(component.configure().id() == State::PRIMARY_STATE_INACTIVE, "configure");
      require(component.activate().id() == State::PRIMARY_STATE_ACTIVE, "activate");
      if (failure == 1) counts.buffer_result = DxlError::ITEM_WRITE_FAIL;
      if (failure == 2) counts.goal_result = DxlError::SYNC_WRITE_FAIL;
      if (failure == 3) raw->dxl_status_ = HW_ERROR;
      const auto result = component.write(clock->now(), rclcpp::Duration::from_seconds(.01));
      if (failure == 0) {
        require(result == Result::OK && counts.disables == 0, "healthy write");
        component.shutdown();
        require(component.get_lifecycle_id() == State::PRIMARY_STATE_FINALIZED, "shutdown final state");
        require(counts.disables >= 2, "shutdown did not attempt both groups");
      } else {
        require(result == Result::ERROR, "fault did not propagate");
        require(counts.disables == 2, "write error did not route to stop");
        require(component.get_lifecycle_id() == State::PRIMARY_STATE_FINALIZED, "fault was recoverable");
        require(counts.goals == (failure == 2 ? 1 : 0), "unexpected goal after fault");
        int goals = counts.goals;
        component.write(clock->now(), rclcpp::Duration::from_seconds(.01));
        component.configure(); component.activate();
        require(counts.goals == goals && component.get_lifecycle_id() == State::PRIMARY_STATE_FINALIZED,
                "fault reopened commands");
        require(raw->on_error(rclcpp_lifecycle::State()) == hardware_interface::CallbackReturn::ERROR && counts.disables == 4,
                "repeated cleanup did not retain fault");
      }
      std::cout << "PASS routing failure=" << failure << " disable_group=" << failed_group << std::endl;
      ++cases;
    }
  }
  rclcpp::shutdown();
  return cases == 12 ? 0 : 1;
} catch (const std::exception & error) {
  std::cerr << "FAIL " << error.what() << std::endl;
  rclcpp::shutdown();
  return 2;
}
