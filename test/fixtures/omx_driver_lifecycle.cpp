// Boundary doubles for the actual pinned vendor start()/stop() method bodies.
// This executable has no ROS runtime, SDK, serial port, or actuator access.
#include <chrono>
#include <cstdint>
#include <iostream>
#include <thread>
#include <utility>
#include <vector>
#define RCLCPP_ERROR_STREAM(...) do {} while (false)
#define RCLCPP_INFO_STREAM(...) do {} while (false)
namespace rclcpp {
struct Duration { Duration(int, int) {} double seconds() const { return 1.0; } };
struct Time {};
Duration operator-(Time, Time) { return Duration(1, 0); }
}
namespace hardware_interface { enum class CallbackReturn { SUCCESS, ERROR }; }
enum class DxlError { OK, ERROR };
using Motors = std::vector<std::pair<uint8_t, uint8_t>>;
struct Comm {
  DxlError read_result = DxlError::OK, write_result = DxlError::OK;
  DxlError enable_result = DxlError::OK;
  int enables = 0, writes = 0, disables = 0, failed_disable = 0;
  bool physical_torque_on = false;
  DxlError ReadMultiDxlData(double) { return read_result; }
  DxlError WriteMultiDxlData() { ++writes; return write_result; }
  DxlError DynamixelEnable(const Motors &) {
    ++enables; physical_torque_on = true; return enable_result;
  }
  DxlError DynamixelDisable(const Motors & motors) {
    auto result = ++disables == failed_disable ? DxlError::ERROR : DxlError::OK;
    if (result == DxlError::OK && !motors.empty() && motors.front().second == 11) {
      physical_torque_on = false;
    }
    return result;
  }
};
struct DynamixelHardware {
  Comm * dxl_comm_;
  DxlError dxl_comm_err_ = DxlError::OK;
  int err_timeout_ms_ = 500;
  Motors torque_enabled_comm_id_id_{{0, 11}}, dxl_comm_id_id_{{0, 11}};
  Motors virtual_dxl_comm_id_id_{{0, 12}};
  explicit DynamixelHardware(Comm * comm) : dxl_comm_(comm) {}
  rclcpp::Time now() { return {}; }
  DxlError CheckError(DxlError result) { return result; }
  void CalcTransmissionToJoint() {}
  void SyncJointCommandWithStates() {}
  void CalcJointToTransmission() {}
  hardware_interface::CallbackReturn start();
  hardware_interface::CallbackReturn stop();
};
// VENDOR_METHODS
int main() {
  using Result = hardware_interface::CallbackReturn;
  int failed = 0;
  auto check = [&](bool pass, const char * name) {
      std::cout << (pass ? "PASS " : "FAIL ") << name << '\n'; failed += !pass;
    };
  {
    Comm comm; comm.write_result = DxlError::ERROR; DynamixelHardware hw(&comm);
    check(hw.start() == Result::ERROR && comm.enables == 0, "initial_write_failure");
  }
  {
    Comm comm; comm.enable_result = DxlError::ERROR; DynamixelHardware hw(&comm);
    check(hw.start() == Result::ERROR && comm.enables == 10 && comm.disables == 2 &&
      !comm.physical_torque_on, "enable_retry_exhaustion");
  }
  {
    Comm comm; comm.enable_result = DxlError::ERROR; comm.failed_disable = 1;
    DynamixelHardware hw(&comm);
    check(hw.start() == Result::ERROR && comm.disables == 2 && comm.physical_torque_on,
      "failed_rollback_stays_error");
  }
  {
    Comm comm; DynamixelHardware hw(&comm);
    check(hw.start() == Result::SUCCESS && comm.enables == 1, "start_success");
  }
  {
    Comm comm; comm.failed_disable = 1; DynamixelHardware hw(&comm);
    check(hw.stop() == Result::ERROR && comm.disables == 2, "first_stop_group_failure");
  }
  {
    Comm comm; comm.failed_disable = 2; DynamixelHardware hw(&comm);
    check(hw.stop() == Result::ERROR && comm.disables == 2, "second_stop_group_failure");
  }
  {
    Comm comm; DynamixelHardware hw(&comm);
    check(hw.stop() == Result::SUCCESS && comm.disables == 2, "stop_success");
  }
  {
    DynamixelHardware hw(nullptr); check(hw.stop() == Result::ERROR, "missing_comm");
  }
  {
    Comm comm; DynamixelHardware hw(&comm); hw.torque_enabled_comm_id_id_.clear();
    check(hw.start() == Result::SUCCESS && comm.enables == 0, "no_automatic_torque");
  }
  {
    Comm comm; comm.read_result = DxlError::ERROR; DynamixelHardware hw(&comm);
    check(hw.start() == Result::ERROR && comm.writes == 0 && comm.enables == 0, "read_timeout");
  }
  return failed;
}
