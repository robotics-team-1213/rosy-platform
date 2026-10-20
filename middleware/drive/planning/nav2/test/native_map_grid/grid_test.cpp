// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <map>
#include <string>
#include <gtest/gtest.h>
#include "rosy_native_map/grid.hpp"

namespace
{
using nav_msgs::msg::OccupancyGrid;
using rosy_native_map::identify;

OccupancyGrid grid()
{
  OccupancyGrid value;
  value.header.frame_id = "map";
  value.header.stamp.nanosec = 20;
  value.info.map_load_time.nanosec = 10;
  value.info.width = 3;
  value.info.height = 2;
  value.info.resolution = .05F;
  value.info.origin.position.x = -1.25;
  value.info.origin.position.y = 2.5;
  value.info.origin.orientation.w = 1.;
  value.data = {-1, 0, 1, 49, 100, -1};
  return value;
}

std::map<std::string, std::string> golden()
{
  const char * path = std::getenv("ROSY_NATIVE_MAP_VECTORS");
  if (!path) {throw std::runtime_error("missing Python golden fixture path");}
  std::ifstream input(path);
  std::map<std::string, std::string> result;
  std::string name, hash;
  while (input >> name >> hash) {result.emplace(name, hash);}
  if (result.size() != 7) {throw std::runtime_error("incomplete golden fixture");}
  return result;
}
}  // namespace

TEST(NativeMapGrid, PythonCanonicalGoldenBytes)
{
  const auto expected = golden();
  auto value = grid();
  EXPECT_EQ(identify(value).digest, expected.at("base"));
  value.info.origin.position.x = -0.;
  EXPECT_EQ(identify(value).digest, expected.at("signed_zero"));
  value.info.origin.position.x = 0.;
  EXPECT_EQ(identify(value).digest, expected.at("positive_zero"));
  EXPECT_NE(expected.at("signed_zero"), expected.at("positive_zero"));
  value = grid();
  value.info.origin.orientation.w = -1.;
  EXPECT_EQ(identify(value).digest, expected.at("quaternion_sign"));
  value = grid();
  value.data[2] = 49;  // Both 1 and 49 become unknown in AMCL, but are different originals.
  EXPECT_EQ(identify(value).digest, expected.at("equal_conversion"));
  EXPECT_NE(identify(value).digest, expected.at("base"));
  value = grid();
  value.header.stamp.nanosec = 21;
  EXPECT_EQ(identify(value).digest, expected.at("time_only"));
  EXPECT_EQ(expected.at("time_only"), expected.at("base"));
  value.header.stamp.nanosec = value.info.map_load_time.nanosec = 0;
  EXPECT_EQ(identify(value).digest, expected.at("static_zero_time"));
}

TEST(NativeMapGrid, FullOriginalIdentityIncludesBothTimes)
{
  const auto original = identify(grid());
  EXPECT_TRUE(original.same_original(identify(grid())));
  auto changed = grid();
  ++changed.header.stamp.nanosec;
  EXPECT_FALSE(original.same_original(identify(changed)));
  changed = grid();
  ++changed.info.map_load_time.nanosec;
  EXPECT_FALSE(original.same_original(identify(changed)));
  changed = grid();
  changed.data[2] = 49;
  EXPECT_FALSE(original.same_original(identify(changed)));
}

TEST(NativeMapGrid, RejectsMalformedShapeFrameCellsAndSizeOverflow)
{
  auto value = grid();
  value.header.frame_id = "odom";
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.width = 0;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.height = 0;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.width = value.info.height = UINT32_MAX;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.data.pop_back();
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.data.push_back(0);
  EXPECT_THROW(identify(value), std::invalid_argument);
  for (const int invalid : {-128, -2, 101, 127}) {
    value = grid(); value.data[0] = static_cast<int8_t>(invalid);
    EXPECT_THROW(identify(value), std::invalid_argument);
  }
}

TEST(NativeMapGrid, RejectsUnsupportedGeometryAndNonfiniteValues)
{
  auto value = grid();
  for (const float invalid : {0.F, -.05F, INFINITY, NAN}) {
    value.info.resolution = invalid;
    EXPECT_THROW(identify(value), std::invalid_argument);
  }
  value = grid(); value.info.origin.position.z = 1e-12;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.orientation.x = 1e-12;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.orientation.y = 1e-12;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.orientation.z = 1e-12;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.orientation.w = 1.000000000001;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.position.x = INFINITY;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.position.y = NAN;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.origin.orientation.w = NAN;
  EXPECT_THROW(identify(value), std::invalid_argument);
}

TEST(NativeMapGrid, ValidatesOriginalTimeWithoutStaticMapTtl)
{
  auto value = grid();
  value.header.stamp.sec = -1;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.header.stamp.nanosec = 1000000000;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.map_load_time.sec = -1;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.map_load_time.nanosec = 1000000000;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.info.map_load_time.nanosec = 21;
  EXPECT_THROW(identify(value), std::invalid_argument);
  value = grid(); value.header.stamp.nanosec = value.info.map_load_time.nanosec = 0;
  EXPECT_NO_THROW(identify(value));
}

TEST(NativeMapGrid, AcceptsExactCellLimitAndRejectsLargerGrid)
{
  auto value = grid();
  value.info.width = value.info.height = 2048;
  value.data.assign(4194304, 0);
  EXPECT_NO_THROW(identify(value));
  ++value.info.height;
  value.data.assign(static_cast<size_t>(value.info.width) * value.info.height, 0);
  EXPECT_THROW(identify(value), std::invalid_argument);
}

TEST(NativeMapGrid, RejectsOversizedOriginalBeforeCallingItsCopier)
{
  auto value = grid();
  int copies = 0;
  auto copy = [&](const OccupancyGrid & original) {
      ++copies;
      EXPECT_EQ(&original, &value);
      return 1;
    };
  value.data.resize(4194305);
  EXPECT_THROW(rosy_native_map::capture_original(value, copy), std::invalid_argument);
  EXPECT_EQ(copies, 0);
  value = grid();
  value.info.width = value.info.height = UINT32_MAX;
  EXPECT_THROW(rosy_native_map::capture_original(value, copy), std::invalid_argument);
  EXPECT_EQ(copies, 0);
  value.info.width = value.info.height = 2048;
  value.data.assign(4194304, 0);
  EXPECT_EQ(rosy_native_map::capture_original(value, copy), 1);
  EXPECT_EQ(copies, 1);
}
