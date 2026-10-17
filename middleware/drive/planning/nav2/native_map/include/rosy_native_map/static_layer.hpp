// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: BSD-3-Clause
#ifndef ROSY_NATIVE_MAP__STATIC_LAYER_HPP_
#define ROSY_NATIVE_MAP__STATIC_LAYER_HPP_
#include <optional>
#include "interfaces/srv/map_adoption.hpp"
#include "nav2_costmap_2d/static_layer.hpp"
#include "rosy_native_map/grid.hpp"
#include "rosy_native_map/support.hpp"

namespace rosy_native_map
{
// One original full map per plugin lifetime. The service reports this layer's
// applied contribution, never final inflated costs or permission to move.
class VerifiedStaticLayer : public nav2_costmap_2d::StaticLayer
{
public:
  VerifiedStaticLayer();
  ~VerifiedStaticLayer() override;
  void activate() override;
  void deactivate() override;
  void reset() override;
  void matchSize() override;
  void updateBounds(double x, double y, double yaw, double * min_x,
    double * min_y, double * max_x, double * max_y) override;
  void updateCosts(nav2_costmap_2d::Costmap2D & master,
    int min_i, int min_j, int max_i, int max_j) override;
protected:
  void onInitialize() override;
private:
  friend struct StaticLayerTestAccess;  // Read-only native fixture inspector.
  using Wire = interfaces::srv::MapAdoption;
  using Costmap = nav2_costmap_2d::Costmap2D;
  void receive(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr & message);
  void readback(const Wire::Request & request, Wire::Response & response);
  void retire(const char * reason);
  bool advance();
  bool supported() const;
  bool active() const;
  bool geometry(const Costmap & grid) const;
  bool cells_match(Costmap & grid);
  const std::array<uint8_t, 16> instance_;
  uint64_t generation_{0};
  uint64_t native_input_count_{0}, native_process_count_{0};
  bool initialized_{false}, activated_{false}, retired_{false};
  bool processing_first_{false}, applied_{false};
  std::string reason_{"map_pending"}, config_digest_;
  std::optional<Identity> original_;
  nav_msgs::msg::OccupancyGrid::ConstSharedPtr original_grid_;
  rclcpp::Service<Wire>::SharedPtr readback_service_;
  rclcpp_lifecycle::LifecycleNode::PreSetParametersCallbackHandle::SharedPtr freeze_;
};
}  // namespace rosy_native_map
#endif  // ROSY_NATIVE_MAP__STATIC_LAYER_HPP_
