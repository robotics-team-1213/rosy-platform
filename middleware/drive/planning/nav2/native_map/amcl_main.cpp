// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: LGPL-2.1-or-later
#include "rosy_native_map/amcl.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rosy_native_map::VerifiedAmcl>();
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node->get_node_base_interface());
  executor.spin();
  executor.remove_node(node->get_node_base_interface());
  node.reset();
  rclcpp::shutdown();
}
