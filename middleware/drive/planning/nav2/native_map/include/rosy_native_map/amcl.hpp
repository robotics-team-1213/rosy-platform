// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: LGPL-2.1-or-later
#ifndef ROSY_NATIVE_MAP__AMCL_HPP_
#define ROSY_NATIVE_MAP__AMCL_HPP_
#include <optional>
#include "interfaces/srv/map_adoption.hpp"
#include "nav2_amcl/amcl_node.hpp"
#include "rosy_native_map/grid.hpp"
#include "rosy_native_map/support.hpp"

namespace rosy_native_map
{
// Initial supported profile is one instance in the standalone verified binary.
// This class is not registered as a composable node. Ordinary AMCL is unchanged.
class VerifiedAmcl : public nav2_amcl::AmclNode
{
public:
  explicit VerifiedAmcl(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());
  ~VerifiedAmcl() override;

protected:
  nav2_util::CallbackReturn on_configure(const rclcpp_lifecycle::State & state) override;
  nav2_util::CallbackReturn on_activate(const rclcpp_lifecycle::State & state) override;
  nav2_util::CallbackReturn on_deactivate(const rclcpp_lifecycle::State & state) override;
  nav2_util::CallbackReturn on_cleanup(const rclcpp_lifecycle::State & state) override;
  nav2_util::CallbackReturn on_shutdown(const rclcpp_lifecycle::State & state) override;
  // Test inspector may observe genuine callback/native-call counts under mutex_.
  uint64_t native_input_count_{0};
  uint64_t native_handle_count_{0};

private:
  using Wire = interfaces::srv::MapAdoption;
  void receive(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr & message);
  bool native_geometry_matches() const;
  bool native_cells_match(const nav_msgs::msg::OccupancyGrid & message) const;
  void readback(const Wire::Request & request, Wire::Response & response);
  void retire(const char * reason);
  void quiesce();  // Never call while holding mutex_.
  StandaloneLease standalone_;
  const std::array<uint8_t, 16> instance_;
  uint64_t generation_{0};
  bool used_{false};
  bool activated_{false};
  bool retired_{false};
  std::string reason_{"map_pending"};
  std::string config_digest_;
  std::optional<Identity> original_;
  nav_msgs::msg::OccupancyGrid::ConstSharedPtr original_grid_;
  rclcpp::Service<Wire>::SharedPtr readback_service_;
  rclcpp_lifecycle::LifecycleNode::PreSetParametersCallbackHandle::SharedPtr freeze_;
};
}  // namespace rosy_native_map
#endif  // ROSY_NATIVE_MAP__AMCL_HPP_
