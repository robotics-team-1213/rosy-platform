// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#ifndef ROSY_NATIVE_MAP__GRID_HPP_
#define ROSY_NATIVE_MAP__GRID_HPP_

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include "nav_msgs/msg/occupancy_grid.hpp"

namespace rosy_native_map
{
inline constexpr uint64_t kMaxOriginalCells = 4194304;

// Original input identity, never evidence of native processing or permission.
struct Identity
{
  std::string digest;
  std::string frame;
  uint32_t width;
  uint32_t height;
  double resolution;
  std::array<double, 7> origin;
  uint64_t source_stamp_ns;
  uint64_t map_load_time_ns;

  bool same_original(const Identity & other) const;
};

// Caller must own an immutable captured input. Full-grid validation/hash belongs
// outside native owner locks and readback callbacks, never in the final writer.
// Throws on malformed/unsupported input or hashing failure; no map is mutated.
Identity identify(const nav_msgs::msg::OccupancyGrid & grid);

template<typename Capture>
auto capture_original(const nav_msgs::msg::OccupancyGrid & grid, Capture capture)
{
  const uint64_t cells = static_cast<uint64_t>(grid.info.width) * grid.info.height;
  if (cells > kMaxOriginalCells || grid.data.size() > kMaxOriginalCells) {
    throw std::invalid_argument("original occupancy grid exceeds capture limit");
  }
  return capture(grid);
}
}  // namespace rosy_native_map

#endif  // ROSY_NATIVE_MAP__GRID_HPP_
