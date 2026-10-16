// Actual read()/CheckError() producer methods; transport and ROS publication are doubled.
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>
#define RCLCPP_ERROR_STREAM(...) do {} while (false)
#define RCLCPP_ERROR_STREAM_THROTTLE(...) do {} while (false)
namespace rclcpp {
struct Time {};
struct Duration {
  double value;
  Duration(int seconds, int nanos) : value(seconds + nanos / 1e9) {}
  double seconds() const { return value; }
};
Duration operator+(Duration a, Duration b) { a.value += b.value; return a; }
bool ok() { return false; }
void spin_some(void *) {}
}
namespace hardware_interface { enum class return_type { OK, ERROR }; }
enum DxlError { OK, ITEM_READ_FAIL, DXL_HARDWARE_ERROR };
enum Status { DXL_OK, COMM_ERROR, HW_ERROR, REBOOTING };
constexpr const char * HW_IF_HARDWARE_STATE = "hardware_state";
struct HardwareErrorStatusBitInfo { const char * label; const char * description; };
struct ErrorCodeInfo { const char * label; const char * description; };
const HardwareErrorStatusBitInfo * get_hardware_error_status_bit_info(int) { return nullptr; }
const ErrorCodeInfo * get_error_code_info(int) { return nullptr; }
struct State {
  uint8_t comm_id = 11, id = 11;
  std::vector<std::string> interface_name_vec;
  std::vector<std::shared_ptr<double>> value_ptr_vec;
};
struct Message {
  struct { int stamp = 0; } header;
  int comm_state = 0;
  std::vector<int> id{0}, dxl_hw_state{0};
  std::vector<bool> torque_state{false};
};
struct Publisher {
  std::vector<Message> messages;
  void try_publish(const Message & message) { messages.push_back(message); }
};
struct Comm {
  DxlError result = DxlError::OK;
  DxlError ReadMultiDxlData(double) { return result; }
  void ReadItemBuf() {}
};
struct DynamixelHardware {
  Comm comm;
  Comm * dxl_comm_ = &comm;
  Status dxl_status_ = DXL_OK;
  DxlError dxl_comm_err_ = DxlError::OK;
  bool is_read_in_error_ = false;
  rclcpp::Duration read_error_duration_{0, 0};
  int err_timeout_ms_ = 500, stamp = 0;
  size_t num_of_transmissions_ = 1, num_of_joints_ = 0;
  std::vector<State> hdl_trans_states_, hdl_joint_states_;
  std::vector<int> hdl_gpio_sensor_states_;
  std::map<int, int> dxl_hw_err_, dxl_error_code_;
  std::map<std::pair<uint8_t, uint8_t>, bool> dxl_torque_state_;
  std::unique_ptr<Publisher> dxl_state_pub_uni_ptr_{new Publisher};
  Message dxl_state_msg_;
  DynamixelHardware() {
    State state;
    state.interface_name_vec = {"Present Position", "Torque Enable", "Hardware Error Status"};
    for (double value : {1.0, 0.0, 0.0}) state.value_ptr_vec.push_back(std::make_shared<double>(value));
    hdl_trans_states_.push_back(state);
  }
  void CalcTransmissionToJoint() {}
  void ReadSensorData(int) {}
  void * get_node_base_interface() { return nullptr; }
  int now() { return ++stamp; }
  DxlError CheckError(DxlError);
  hardware_interface::return_type read(const rclcpp::Time &, const rclcpp::Duration &);
};
// VENDOR_METHODS
int main() {
  using Result = hardware_interface::return_type;
  const rclcpp::Duration period(0, 10000000);
  int failed = 0;
  auto check = [&](const std::function<bool()> & test, const char * name) {
    bool pass = false;
    try { pass = test(); } catch (...) {}
    std::cout << (pass ? "PASS " : "FAIL ") << name << '\n'; failed += !pass;
  };
  check([&] {
    DynamixelHardware d; *d.hdl_trans_states_[0].value_ptr_vec[1] = 1;
    return d.read({}, period) == Result::OK && d.dxl_state_pub_uni_ptr_->messages.size() == 1 &&
      d.dxl_state_pub_uni_ptr_->messages[0].torque_state[0];
  }, "measured_torque_on_is_published");
  check([&] {
    DynamixelHardware d; d.dxl_torque_state_[{11, 11}] = true;
    return d.read({}, period) == Result::OK && !d.dxl_state_pub_uni_ptr_->messages[0].torque_state[0];
  }, "measured_torque_off_replaces_previous_state");
  check([&] {
    DynamixelHardware d; *d.hdl_trans_states_[0].value_ptr_vec[2] = 16;
    return d.read({}, period) == Result::ERROR && d.dxl_state_pub_uni_ptr_->messages.size() == 1 &&
      d.dxl_state_pub_uni_ptr_->messages[0].dxl_hw_state[0] == 16 &&
      d.dxl_state_pub_uni_ptr_->messages[0].comm_state == DxlError::DXL_HARDWARE_ERROR;
  }, "measured_hardware_fault_is_published_and_rejected");
  for (int invalid : {0, 1, 2, 3, 4, 5, 6, 7}) {
    check([&] {
      DynamixelHardware d; auto & s = d.hdl_trans_states_[0];
      if (invalid == 0) s.interface_name_vec[1] = "unrelated";
      if (invalid == 1) s.interface_name_vec[2] = "unrelated";
      if (invalid == 2) *s.value_ptr_vec[1] = std::numeric_limits<double>::quiet_NaN();
      if (invalid == 3) *s.value_ptr_vec[1] = 2;
      if (invalid == 4) *s.value_ptr_vec[2] = .5;
      if (invalid == 5) { s.interface_name_vec.push_back("Torque Enable"); s.value_ptr_vec.push_back(s.value_ptr_vec[1]); }
      if (invalid == 6) s.value_ptr_vec[1].reset();
      if (invalid == 7) s.value_ptr_vec.pop_back();
      return d.read({}, period) == Result::ERROR && d.dxl_state_pub_uni_ptr_->messages.empty();
    }, ("invalid_status_" + std::to_string(invalid)).c_str());
  }
  check([&] {
    DynamixelHardware d; d.comm.result = DxlError::ITEM_READ_FAIL;
    return d.read({}, period) == Result::ERROR && d.dxl_state_pub_uni_ptr_->messages.empty();
  }, "failed_read_is_immediate_without_fresh_status");
  check([&] {
    DynamixelHardware d;
    if (d.read({}, period) != Result::OK) return false;
    *d.hdl_trans_states_[0].value_ptr_vec[1] = 1;
    return d.read({}, period) == Result::OK && d.dxl_state_pub_uni_ptr_->messages.size() == 2 &&
      !d.dxl_state_pub_uni_ptr_->messages[0].torque_state[0] && d.dxl_state_pub_uni_ptr_->messages[1].torque_state[0] &&
      d.dxl_state_pub_uni_ptr_->messages[0].header.stamp < d.dxl_state_pub_uni_ptr_->messages[1].header.stamp;
  }, "next_cycle_uses_new_measurement");
  check([&] {
    DynamixelHardware d; d.hdl_trans_states_.clear(); d.num_of_transmissions_ = 0;
    return d.read({}, period) == Result::ERROR && d.dxl_state_pub_uni_ptr_->messages.empty();
  }, "no_motor_states_are_not_healthy");
  return failed;
}
