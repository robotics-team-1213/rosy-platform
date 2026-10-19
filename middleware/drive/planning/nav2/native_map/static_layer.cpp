/*********************************************************************
 * Software License Agreement (BSD License)
 * Copyright (c) 2008, 2013, Willow Garage, Inc.
 * Copyright (c) 2015, Fetch Robotics, Inc.
 * Copyright 2026 ROSY contributors.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *   * Redistributions of source code must retain the above copyright
 *     notice, this list of conditions and the following disclaimer.
 *   * Redistributions in binary form must reproduce the above
 *     copyright notice, this list of conditions and the following
 *     disclaimer in the documentation and/or other materials provided
 *     with the distribution.
 *   * Neither the name of Willow Garage, Inc. nor the names of its
 *     contributors may be used to endorse or promote products derived
 *     from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 * Startup wiring adapted from Nav2 static_layer.cpp, authors Eitan
 * Marder-Eppstein and David V. Lu!!, commit
 * f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501.
 * Native map conversion/application remain in the upstream library.
 * SPDX-License-Identifier: BSD-3-Clause
 *********************************************************************/
#include "rosy_native_map/static_layer.hpp"
#include <limits>
#include "lifecycle_msgs/msg/state.hpp"
#include "pluginlib/class_list_macros.hpp"
#include "rosy_native_map/build_id.hpp"

PLUGINLIB_EXPORT_CLASS(rosy_native_map::VerifiedStaticLayer, nav2_costmap_2d::Layer)

namespace rosy_native_map
{
VerifiedStaticLayer::VerifiedStaticLayer() : instance_(new_instance_id()) {}

VerifiedStaticLayer::~VerifiedStaticLayer()
{
  // Costmap2DROS joins its private executor before releasing plugins. A retained
  // shared_ptr may outlive that parent: never dereference layered_costmap_ here.
  readback_service_.reset(); map_sub_.reset(); freeze_.reset();
  auto node = node_.lock();
  if (node && dyn_params_handler_) {node->remove_on_set_parameters_callback(dyn_params_handler_.get());}
  dyn_params_handler_.reset();
}

bool VerifiedStaticLayer::advance()
{
  if (generation_ == std::numeric_limits<uint64_t>::max()) {
    retired_ = true; applied_ = false; reason_ = "generation_exhausted"; return false;
  }
  ++generation_; return true;
}

void VerifiedStaticLayer::retire(const char * reason)
{
  if (!retired_) {advance(); retired_ = true; applied_ = false; reason_ = reason;}
}

bool VerifiedStaticLayer::supported() const
{
  return enabled_ && !layered_costmap_->isRolling() && !use_maximum_ &&
         !subscribe_to_updates_ && map_subscribe_transient_local_ &&
         !footprint_clearing_enabled_ && global_frame_ == "map" &&
         unknown_cost_value_ == 255 && lethal_threshold_ > 0 && lethal_threshold_ <= 100 &&
         layered_costmap_->getFilters()->empty();
}

void VerifiedStaticLayer::onInitialize()
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (initialized_) {retire("initialize_reused"); throw std::runtime_error("plugin lifetime reused");}
  initialized_ = true; current_ = false;
  global_frame_ = layered_costmap_->getGlobalFrameID();
  getParameters();  // Never base onInitialize: no unguarded subscription exists.
  auto node = node_.lock();
  if (!node || !callback_group_ || !supported() ||
    node->get_parameter("lethal_cost_threshold").as_int() < 1 ||
    node->get_parameter("lethal_cost_threshold").as_int() > 100 ||
    node->get_parameter("unknown_cost_value").as_int() != 255 ||
    !node->get_parameter("filters").as_string_array().empty() ||
    std::string(node->get_fully_qualified_name()).size() > 256)
  {
    retire("unsupported_configuration"); throw std::runtime_error("unsupported verified static profile");
  }
  rclcpp::SubscriptionOptions options; options.callback_group = callback_group_;
  map_sub_ = node->create_subscription<nav_msgs::msg::OccupancyGrid>(
    map_topic_, rclcpp::QoS(1).transient_local().reliable(),
    [this](nav_msgs::msg::OccupancyGrid::ConstSharedPtr msg) {receive(msg);}, options);
  config_digest_ = parameter_digest(*node, map_sub_->get_topic_name());
  // Pinned API rejects the whole mixed transaction before inherited on-set work.
  freeze_ = node->add_pre_set_parameters_callback(
    [](std::vector<rclcpp::Parameter> & parameters) {parameters.clear();});
  readback_service_ = node->create_service<Wire>(
    name_ + "/map_adoption", [this](Wire::Request::SharedPtr request, Wire::Response::SharedPtr reply) {
      readback(*request, *reply);
    }, rmw_qos_profile_services_default, callback_group_);
}

bool VerifiedStaticLayer::geometry(const Costmap & grid) const
{
  return original_ && grid.getCharMap() && grid.getSizeInCellsX() == original_->width &&
         grid.getSizeInCellsY() == original_->height && grid.getResolution() == original_->resolution &&
         grid.getOriginX() == original_->origin[0] && grid.getOriginY() == original_->origin[1];
}

bool VerifiedStaticLayer::cells_match(Costmap & grid)
{
  for (size_t i = 0; i < original_grid_->data.size(); ++i) {
    if (grid.getCharMap()[i] != interpretValue(static_cast<unsigned char>(original_grid_->data[i]))) {
      return false;
    }
  }
  return true;
}

void VerifiedStaticLayer::receive(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr & message)
{
  bool counted = false;
  try {
    if (message->data.size() > 4194304) {throw std::runtime_error("oversized map");}
    auto captured = std::make_shared<const nav_msgs::msg::OccupancyGrid>(*message);
    const auto identity = identify(*captured);  // Hash outside BOTH native locks.
    std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
    std::lock_guard<Costmap::mutex_t> local(*getMutex());
    if (native_input_count_ == std::numeric_limits<uint64_t>::max()) {retire("counter_exhausted"); return;}
    ++native_input_count_;
    counted = true;
    if (retired_) {return;}
    if (original_) {
      if (!original_->same_original(identity)) {retire("original_changed");}
      return;
    }
    if (!supported()) {retire("unsupported_configuration"); return;}
    processing_first_ = true;
    ++native_process_count_;
    try {processMap(*captured);} catch (...) {processing_first_ = false; throw;}
    processing_first_ = false;
    original_ = identity; original_grid_ = captured; map_received_ = true;
    if (!geometry(*this) || !geometry(*layered_costmap_->getCostmap()) || !cells_match(*this)) {
      retire("native_map_mismatch"); return;
    }
    if (advance()) {reason_ = "application_pending";}
  } catch (const std::exception &) {
    std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
    std::lock_guard<Costmap::mutex_t> local(*getMutex());
    if (!counted && native_input_count_ < std::numeric_limits<uint64_t>::max()) {++native_input_count_;}
    retire("invalid_original_or_native_failure");
  }
}

bool VerifiedStaticLayer::active() const
{
  auto node = node_.lock();
  return activated_ && node &&
         node->get_current_state().id() == lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE;
}

void VerifiedStaticLayer::activate()
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (activated_) {retire("activation_reused");}
  if (!retired_) {activated_ = true; nav2_costmap_2d::StaticLayer::activate();}
}

void VerifiedStaticLayer::deactivate()
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  retire("deactivated"); activated_ = false;
  nav2_costmap_2d::StaticLayer::deactivate();
}

void VerifiedStaticLayer::reset()
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  applied_ = false; map_received_in_update_bounds_ = false;
  if (!retired_ && advance()) {reason_ = "application_pending";}
  nav2_costmap_2d::StaticLayer::reset();
}

void VerifiedStaticLayer::matchSize()
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (original_ && !processing_first_) {retire("external_resize");}
  nav2_costmap_2d::StaticLayer::matchSize();
}

void VerifiedStaticLayer::updateBounds(double x, double y, double yaw, double * min_x,
  double * min_y, double * max_x, double * max_y)
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (retired_) {return;}
  // Parent begins its update thread while ACTIVATING. Replay full bounds until
  // a genuine full application happens with the actual parent already ACTIVE.
  if (original_ && !applied_) {has_updated_data_ = true;}
  nav2_costmap_2d::StaticLayer::updateBounds(x, y, yaw, min_x, min_y, max_x, max_y);
}

void VerifiedStaticLayer::updateCosts(Costmap & target, int min_i, int min_j, int max_i, int max_j)
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (retired_) {return;}
  if (!supported() || &target != layered_costmap_->getCostmap()) {retire("unsupported_application"); return;}
  if (original_ && (!geometry(*this) || !geometry(target) || map_frame_ != "map")) {
    retire("native_map_lost"); return;
  }
  nav2_costmap_2d::StaticLayer::updateCosts(target, min_i, min_j, max_i, max_j);
  if (!applied_ && original_ && active() && map_received_ && map_received_in_update_bounds_ &&
    min_i == 0 && min_j == 0 && max_i == static_cast<int>(original_->width) &&
    max_j == static_cast<int>(original_->height))
  {
    if (!cells_match(*this) || !cells_match(target)) {retire("native_application_mismatch"); return;}
    if (advance()) {applied_ = true; reason_ = "adopted";}
  }
}

void VerifiedStaticLayer::readback(const Wire::Request & request, Wire::Response & response)
{
  std::lock_guard<Costmap::mutex_t> master(*layered_costmap_->getCostmap()->getMutex());
  std::lock_guard<Costmap::mutex_t> local(*getMutex());
  if (!retired_ && (!supported() || (original_ &&
    (!map_received_ || !geometry(*this) || !geometry(*layered_costmap_->getCostmap()) || map_frame_ != "map"))))
  {retire("native_map_lost");}
  response.contract_version = Wire::Response::CONTRACT_VERSION;
  response.challenge = request.challenge; response.instance_id = instance_; response.generation = generation_;
  response.active = active(); response.adopted = response.active && !retired_ && applied_;
  response.reason = reason_; response.role = "static_layer";
  if (auto node = node_.lock()) {response.node_fqn = node->get_fully_qualified_name();}
  response.build_id = kBuildId; response.config_digest = config_digest_;
  if (original_) {
    response.grid_digest = original_->digest; response.frame_id = original_->frame;
    response.width = original_->width; response.height = original_->height;
    response.resolution = original_->resolution; response.origin = original_->origin;
    response.source_stamp_ns = original_->source_stamp_ns; response.map_load_time_ns = original_->map_load_time_ns;
  }
}
}  // namespace rosy_native_map
