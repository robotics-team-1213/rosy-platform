/*
 * Copyright (c) 2008, Willow Garage, Inc. All rights reserved.
 * Copyright 2026 ROSY contributors.
 *
 * The configure composition and publisher/subscriber wiring below are adapted
 * from nav2_amcl/src/amcl_node.cpp, Nav2 commit
 * f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501 (Author: Brian Gerkey).
 * Localization and map-conversion algorithms remain in the upstream library.
 *
 * This library is free software; you can redistribute it and/or modify it under
 * the terms of the GNU Lesser General Public License as published by the Free
 * Software Foundation; either version 2.1 of the License, or (at your option)
 * any later version. This library is distributed in the hope that it will be
 * useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser
 * General Public License for more details. You should have received a copy of
 * that license with this library; if not, write to the Free Software Foundation,
 * Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA.
 * SPDX-License-Identifier: LGPL-2.1-or-later
 */
#include "rosy_native_map/amcl.hpp"
#include <limits>
#include "lifecycle_msgs/msg/state.hpp"
#include "rosy_native_map/build_id.hpp"

namespace rosy_native_map
{
VerifiedAmcl::VerifiedAmcl(const rclcpp::NodeOptions & options)
: nav2_amcl::AmclNode(options), instance_(new_instance_id())
{
  if (options.use_intra_process_comms()) {
    throw std::runtime_error("verified AMCL supports standalone DDS input only");
  }
}

VerifiedAmcl::~VerifiedAmcl()
{
  {std::lock_guard<std::recursive_mutex> lock(mutex_); retire("destroyed");}
  quiesce();  // Derived callback state must survive until its executor is joined.
  readback_service_.reset();
  if (pf_) {nav2_amcl::AmclNode::on_cleanup(rclcpp_lifecycle::State());}
}

void VerifiedAmcl::retire(const char * reason)
{
  if (!retired_) {
    retired_ = true;
    reason_ = reason;
    if (generation_ < std::numeric_limits<uint64_t>::max()) {++generation_;}
  }
}

void VerifiedAmcl::quiesce()
{
  if (executor_) {executor_->cancel();}
  executor_thread_.reset();
}

nav2_util::CallbackReturn VerifiedAmcl::on_configure(const rclcpp_lifecycle::State &)
{
  try {
    {
      std::lock_guard<std::recursive_mutex> lock(mutex_);
      if (used_ || retired_) {retire("configure_reused"); return nav2_util::CallbackReturn::FAILURE;}
      used_ = true;
      initParameters();
      if (global_frame_id_ != "map" || base_frame_id_.empty() || odom_frame_id_.empty() ||
        base_frame_id_.size() > 128 || odom_frame_id_.size() > 128 ||
        std::string(get_fully_qualified_name()).size() > 256)
      {
        retire("unsupported_configuration");
        return nav2_util::CallbackReturn::FAILURE;
      }
      callback_group_ = create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive, false);
      initTransforms();
      initParticleFilter();
      initLaserScan();
      initMessageFilters();
      // Do not call base on_configure/initPubSub: no unguarded map callback exists,
      // including startup with a transient-local map already waiting.
      particle_cloud_pub_ = create_publisher<nav2_msgs::msg::ParticleCloud>(
        "particle_cloud", rclcpp::SensorDataQoS());
      pose_pub_ = create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>(
        "amcl_pose", rclcpp::QoS(1).transient_local().reliable());
      rclcpp::SubscriptionOptions options;
      options.callback_group = callback_group_;
      initial_pose_sub_ = create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
        "initialpose", rclcpp::SystemDefaultsQoS(),
        [this](geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg) {
          initialPoseReceived(msg);
        }, options);
      map_sub_ = create_subscription<nav_msgs::msg::OccupancyGrid>(
        map_topic_, rclcpp::QoS(1).transient_local().reliable(),
        [this](nav_msgs::msg::OccupancyGrid::ConstSharedPtr msg) {receive(msg);}, options);
      initServices();
      initOdometry();
      config_digest_ = parameter_digest(*this, map_sub_->get_topic_name());
      // The pinned pre-set API rejects the WHOLE transaction before inherited
      // on-set callbacks. In particular, map_topic cannot silently re-subscribe.
      freeze_ = add_pre_set_parameters_callback(
        [](std::vector<rclcpp::Parameter> & parameters) {parameters.clear();});
      readback_service_ = create_service<Wire>(
        "~/map_adoption", [this](Wire::Request::SharedPtr request, Wire::Response::SharedPtr reply) {
          readback(*request, *reply);
        }, rmw_qos_profile_services_default, callback_group_);
      executor_ = std::make_shared<rclcpp::executors::SingleThreadedExecutor>();
      executor_->add_callback_group(callback_group_, get_node_base_interface());
    }
    // All owned endpoints/state are ready before any private callback can run.
    executor_thread_ = std::make_unique<nav2_util::NodeThread>(executor_);
    return nav2_util::CallbackReturn::SUCCESS;
  } catch (const std::exception & error) {
    {std::lock_guard<std::recursive_mutex> lock(mutex_); retire("configure_failed");}
    quiesce();
    RCLCPP_ERROR(get_logger(), "Verified AMCL configure failed: %s", error.what());
    return nav2_util::CallbackReturn::FAILURE;
  }
}

nav2_util::CallbackReturn VerifiedAmcl::on_activate(const rclcpp_lifecycle::State & state)
{
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (retired_ || activated_) {retire("activation_reused"); return nav2_util::CallbackReturn::FAILURE;}
  const auto result = nav2_amcl::AmclNode::on_activate(state);
  if (result == nav2_util::CallbackReturn::SUCCESS) {activated_ = true;} else {retire("activation_failed");}
  return result;
}

nav2_util::CallbackReturn VerifiedAmcl::on_deactivate(const rclcpp_lifecycle::State & state)
{
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  retire("deactivated");
  return nav2_amcl::AmclNode::on_deactivate(state);
}

nav2_util::CallbackReturn VerifiedAmcl::on_cleanup(const rclcpp_lifecycle::State & state)
{
  {std::lock_guard<std::recursive_mutex> lock(mutex_); retire("cleaned_up");}
  quiesce();
  readback_service_.reset();
  return nav2_amcl::AmclNode::on_cleanup(state);
}

nav2_util::CallbackReturn VerifiedAmcl::on_shutdown(const rclcpp_lifecycle::State & state)
{
  {std::lock_guard<std::recursive_mutex> lock(mutex_); retire("shutdown");}
  quiesce();
  readback_service_.reset();
  return nav2_amcl::AmclNode::on_shutdown(state);
}

bool VerifiedAmcl::native_geometry_matches() const
{
  return original_ && map_ && map_->cells &&
         map_->size_x == static_cast<int>(original_->width) &&
         map_->size_y == static_cast<int>(original_->height) && map_->scale == original_->resolution &&
         map_->origin_x == original_->origin[0] + (original_->width / 2) * original_->resolution &&
         map_->origin_y == original_->origin[1] + (original_->height / 2) * original_->resolution;
}

bool VerifiedAmcl::native_cells_match(const nav_msgs::msg::OccupancyGrid & message) const
{
  for (size_t i = 0; i < message.data.size(); ++i) {
    const int expected = message.data[i] == 0 ? -1 : (message.data[i] == 100 ? 1 : 0);
    if (map_->cells[i].occ_state != expected) {return false;}
  }
  return true;
}

void VerifiedAmcl::receive(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr & message)
{
  try {
    // Own the immutable original before hashing; none of this runs in readback.
    auto captured = capture_original(*message, [](const auto & original) {
        return std::make_shared<const nav_msgs::msg::OccupancyGrid>(original);
      });
    const auto identity = identify(*captured);
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (native_input_count_ == std::numeric_limits<uint64_t>::max()) {retire("counter_exhausted"); return;}
    ++native_input_count_;
    if (retired_) {return;}
    if (original_) {
      if (!original_->same_original(identity)) {retire("original_changed");}
      return;  // Exact repeat does not call native code or increment generation.
    }
    if (generation_ == std::numeric_limits<uint64_t>::max()) {retire("generation_exhausted"); return;}
    ++native_handle_count_;
    handleMapMessage(*captured);  // The genuine upstream owner processes THIS raw input once.
    original_ = identity;
    original_grid_ = captured;
    if (!native_geometry_matches() || !native_cells_match(*captured)) {retire("native_map_mismatch"); return;}
    first_map_received_ = true;
    ++generation_;
    reason_ = "adopted";
  } catch (const std::exception &) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    retire("invalid_original_or_native_failure");
  }
}

void VerifiedAmcl::readback(const Wire::Request & request, Wire::Response & response)
{
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (original_ && !retired_ && (!first_map_received_ || !native_geometry_matches())) {
    retire("native_map_lost");
  }
  response.contract_version = Wire::Response::CONTRACT_VERSION;
  response.challenge = request.challenge;
  response.instance_id = instance_;
  response.generation = generation_;
  response.active = active_ &&
    get_current_state().id() == lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE;
  response.adopted = response.active && !retired_ && original_.has_value();
  response.reason = reason_;
  response.role = "amcl";
  response.node_fqn = get_fully_qualified_name();
  response.build_id = kBuildId;
  response.config_digest = config_digest_;
  if (original_) {
    response.grid_digest = original_->digest;
    response.frame_id = original_->frame;
    response.width = original_->width;
    response.height = original_->height;
    response.resolution = original_->resolution;
    response.origin = original_->origin;
    response.source_stamp_ns = original_->source_stamp_ns;
    response.map_load_time_ns = original_->map_load_time_ns;
  }
}
}  // namespace rosy_native_map
