// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#ifndef ROSY_NATIVE_MAP__SUPPORT_HPP_
#define ROSY_NATIVE_MAP__SUPPORT_HPP_
#include <array>
#include <string>
#include "rclcpp_lifecycle/lifecycle_node.hpp"

namespace rosy_native_map
{
std::array<uint8_t, 16> new_instance_id();
std::string sha256(const std::string & bytes);
std::string parameter_digest(rclcpp_lifecycle::LifecycleNode & node, const std::string & topic);

// NEW_UNIFORM_SAMPLING in the pinned AMCL has process-global free-space state.
// The verified binary exports no component and owns just one AMCL lifetime.
class StandaloneLease
{
public:
  StandaloneLease();
  ~StandaloneLease();
  StandaloneLease(const StandaloneLease &) = delete;
  StandaloneLease & operator=(const StandaloneLease &) = delete;
};
}  // namespace rosy_native_map
#endif  // ROSY_NATIVE_MAP__SUPPORT_HPP_
