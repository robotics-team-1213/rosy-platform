// Compile the actual pinned vendor write() at the communication boundary.
// No ROS node, SDK, serial port, or actuator is used.
#include <iostream>
#define RCLCPP_ERROR_STREAM(...) do {} while (false)
namespace rclcpp {
struct Time {};
struct Duration {
  double value;
  Duration(int seconds, int nanoseconds) : value(seconds + nanoseconds / 1e9) {}
  double seconds() const { return value; }
};
Duration operator+(Duration a, Duration b) {
  Duration result(0, 0); result.value = a.value + b.value; return result;
}
}
namespace hardware_interface { enum class return_type { OK, ERROR }; }
enum class DxlError { OK, ITEM_WRITE_FAIL, SYNC_WRITE_FAIL };
enum Status { DXL_OK, HW_ERROR, COMM_ERROR, REBOOTING };
struct Comm {
  DxlError buffer_result = DxlError::OK, goal_result = DxlError::OK;
  int buffers = 0, goals = 0;
  DxlError WriteItemBuf() { ++buffers; return buffer_result; }
  DxlError WriteMultiDxlData() { ++goals; return goal_result; }
};
struct DynamixelHardware {
  Comm * dxl_comm_;
  DxlError dxl_comm_err_ = DxlError::OK;
  Status dxl_status_ = DXL_OK;
  bool is_write_in_error_ = false;
  rclcpp::Duration write_error_duration_{0, 0};
  int err_timeout_ms_ = 500, torque_changes = 0, conversions = 0;
  explicit DynamixelHardware(Comm * comm) : dxl_comm_(comm) {}
  DxlError CheckError(DxlError result) {
    dxl_status_ = result == DxlError::OK ? DXL_OK : COMM_ERROR; return result;
  }
  void ChangeDxlTorqueState() { ++torque_changes; }
  void CalcJointToTransmission() { ++conversions; }
  hardware_interface::return_type write(const rclcpp::Time &, const rclcpp::Duration &);
};
// VENDOR_METHOD
int main() {
  using Result = hardware_interface::return_type;
  int failed = 0;
  auto check = [&](bool pass, const char * name) {
    std::cout << (pass ? "PASS " : "FAIL ") << name << '\n'; failed += !pass;
  };
  const rclcpp::Duration period(0, 10000000);
  {
    Comm comm; DynamixelHardware hw(&comm);
    hw.is_write_in_error_ = true; hw.write_error_duration_ = rclcpp::Duration(1, 0);
    check(hw.write({}, period) == Result::OK && comm.buffers == 1 && comm.goals == 1 &&
      hw.torque_changes == 1 && hw.conversions == 1 && !hw.is_write_in_error_ &&
      hw.write_error_duration_.seconds() == 0, "healthy_write");
  }
  {
    Comm comm; comm.buffer_result = DxlError::ITEM_WRITE_FAIL; DynamixelHardware hw(&comm);
    check(hw.write({}, period) == Result::ERROR && comm.buffers == 1 && comm.goals == 0 &&
      hw.torque_changes == 0 && hw.conversions == 0 && hw.is_write_in_error_, "buffer_failure_stops_goal");
  }
  {
    Comm comm; comm.goal_result = DxlError::SYNC_WRITE_FAIL; DynamixelHardware hw(&comm);
    check(hw.write({}, period) == Result::ERROR && comm.goals == 1 && hw.is_write_in_error_,
      "goal_failure_is_error");
  }
  for (auto status : {HW_ERROR, COMM_ERROR, REBOOTING}) {
    Comm comm; DynamixelHardware hw(&comm); hw.dxl_status_ = status;
    const char * name = status == HW_ERROR ? "hardware_fault_rejects_goal" :
      status == COMM_ERROR ? "communication_fault_is_immediate" : "rebooting_is_immediate";
    check(hw.write({}, period) == Result::ERROR && comm.buffers == 0 && comm.goals == 0 &&
      hw.torque_changes == 0 && hw.is_write_in_error_, name);
  }
  return failed;
}
