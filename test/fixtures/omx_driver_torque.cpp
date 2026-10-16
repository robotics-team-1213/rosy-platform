// Actual SDK-wrapper methods with delivery and acknowledgement modeled separately.
// No SDK, ROS, serial port, or physical actuator is accessed.
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>
enum class DxlError { OK, ITEM_WRITE_FAIL };
constexpr bool TORQUE_OFF = false, TORQUE_ON = true;
using Key = std::pair<uint8_t, uint8_t>;
using Motors = std::vector<Key>;
struct Info { bool CheckDxlControlItem(uint8_t, uint8_t, const char *) { return true; } };
struct Dynamixel {
  Info dxl_info_;
  std::map<Key, bool> torque_state_, physical_state;
  std::set<Key> torque_write_uncertain_;
  std::vector<int> acknowledgements;
  std::vector<bool> deliveries;
  size_t writes = 0;
  int WriteItem(uint8_t comm, uint8_t id, const char *, bool on) {
    size_t index = writes++;
    if (index >= deliveries.size() || deliveries[index]) physical_state[{comm, id}] = on;
    return index < acknowledgements.size() ? acknowledgements[index] : 0;
  }
  DxlError DynamixelEnable(const Motors &);
  DxlError DynamixelDisable(const Motors &);
};
// VENDOR_METHODS
int main() {
  const Motors one{{0, 11}}, two{{0, 11}, {0, 12}};
  const Key a{0, 11}, b{0, 12};
  int failed = 0;
  auto check = [&](bool pass, const char * name) {
    std::cout << (pass ? "PASS " : "FAIL ") << name << '\n'; failed += !pass;
  };
  {
    Dynamixel d; d.acknowledgements = {-1, 0};
    bool error = d.DynamixelEnable(one) == DxlError::ITEM_WRITE_FAIL && d.physical_state[a];
    check(error && d.DynamixelDisable(one) == DxlError::OK && !d.physical_state[a] && d.writes == 2,
      "lost_enable_ack_requires_disable");
  }
  {
    Dynamixel d; d.acknowledgements = {0, -1, 0, 0};
    bool error = d.DynamixelEnable(two) == DxlError::ITEM_WRITE_FAIL;
    check(error && d.DynamixelDisable(two) == DxlError::OK &&
      !d.physical_state[a] && !d.physical_state[b] && d.writes == 4, "partial_enable_ack_requires_all_disable");
  }
  {
    Dynamixel d; d.acknowledgements = {-1, -1, 0};
    bool errors = d.DynamixelEnable(one) == DxlError::ITEM_WRITE_FAIL &&
      d.DynamixelEnable(one) == DxlError::ITEM_WRITE_FAIL;
    check(errors && d.DynamixelDisable(one) == DxlError::OK && !d.physical_state[a] && d.writes == 3,
      "repeated_enable_timeout_never_claims_success");
  }
  {
    Dynamixel d;
    check(d.DynamixelEnable(one) == DxlError::OK && d.DynamixelDisable(one) == DxlError::OK &&
      !d.physical_state[a] && d.writes == 2, "normal_round_trip");
  }
  {
    Dynamixel d; d.torque_state_[a] = true; d.physical_state[a] = true;
    d.acknowledgements = {-1, 0};
    bool error = d.DynamixelDisable(one) == DxlError::ITEM_WRITE_FAIL;
    check(error && d.DynamixelDisable(one) == DxlError::OK && !d.physical_state[a] && d.writes == 2,
      "disable_timeout_remains_retryable");
  }
  {
    // Failed passive initialization must not power down an already-active arm:
    // there has been no activation write by this object, hence no ownership.
    Dynamixel d; d.torque_state_[a] = false; d.physical_state[a] = true;
    check(d.DynamixelDisable(one) == DxlError::OK && d.physical_state[a] && d.writes == 0,
      "passive_rejection_does_not_cut_existing_torque");
  }
  {
    Dynamixel d; d.acknowledgements = {-1, 0, 0};
    bool error = d.DynamixelEnable(one) == DxlError::ITEM_WRITE_FAIL;
    check(error && d.DynamixelEnable(one) == DxlError::OK && d.DynamixelDisable(one) == DxlError::OK &&
      !d.physical_state[a] && d.writes == 3, "enable_retry_success");
  }
  {
    Dynamixel d; d.torque_state_[a] = d.torque_state_[b] = true;
    d.physical_state[a] = d.physical_state[b] = true; d.acknowledgements = {-1, 0};
    check(d.DynamixelDisable(two) == DxlError::ITEM_WRITE_FAIL && !d.physical_state[b] && d.writes == 2,
      "disable_attempts_other_ids_after_failure");
  }
  {
    Dynamixel d; d.acknowledgements = {-1, 0}; d.deliveries = {false, true};
    bool error = d.DynamixelEnable(one) == DxlError::ITEM_WRITE_FAIL;
    check(error && d.DynamixelDisable(one) == DxlError::OK && !d.physical_state[a] && d.writes == 2,
      "undelivered_enable_still_requires_disable");
  }
  return failed;
}
