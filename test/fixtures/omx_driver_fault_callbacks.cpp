// Actual vendor error/shutdown and stop methods, with only bus calls doubled.
#include <iostream>
#include <vector>
#define RCLCPP_ERROR_STREAM(...) do {} while (false)
#define RCLCPP_INFO_STREAM(...) do {} while (false)
namespace hardware_interface { enum class CallbackReturn { SUCCESS, ERROR }; }
namespace rclcpp_lifecycle { struct State {}; }
enum class DxlError { OK, ERROR };
struct Comm {
  int disables = 0, failed_group = 0;
  DxlError DynamixelDisable(const std::vector<int> &) {
    return ++disables == failed_group ? DxlError::ERROR : DxlError::OK;
  }
};
struct DynamixelHardware {
  Comm * dxl_comm_;
  std::vector<int> dxl_comm_id_id_{11}, virtual_dxl_comm_id_id_{12};
  hardware_interface::CallbackReturn stop();
  hardware_interface::CallbackReturn on_error(const rclcpp_lifecycle::State &);
  hardware_interface::CallbackReturn on_shutdown(const rclcpp_lifecycle::State &);
};
// VENDOR_METHODS
int main() {
  using Result = hardware_interface::CallbackReturn;
  int failed = 0;
  for (bool shutdown : {false, true}) {
    for (int group : {0, 1, 2}) {
      Comm comm; comm.failed_group = group; DynamixelHardware driver{&comm};
      auto result = shutdown ? driver.on_shutdown({}) : driver.on_error({});
      bool pass = result == (shutdown && group == 0 ? Result::SUCCESS : Result::ERROR) && comm.disables == 2;
      std::cout << (pass ? "PASS " : "FAIL ") << (shutdown ? "shutdown" : "error") << "_group_" << group << '\n';
      failed += !pass;
    }
    DynamixelHardware driver{nullptr};
    auto result = shutdown ? driver.on_shutdown({}) : driver.on_error({});
    bool pass = result == Result::ERROR;
    std::cout << (pass ? "PASS " : "FAIL ") << (shutdown ? "shutdown" : "error") << "_no_comm\n";
    failed += !pass;
  }
  return failed;
}
