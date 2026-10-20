// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include "rosy_native_map/grid.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>
#include <openssl/evp.h>

namespace rosy_native_map
{
namespace
{
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

uint64_t timestamp(const builtin_interfaces::msg::Time & value)
{
  if (value.sec < 0 || value.nanosec >= 1000000000) {
    throw std::invalid_argument("invalid original grid timestamp");
  }
  return static_cast<uint64_t>(value.sec) * 1000000000 + value.nanosec;
}

class Digest
{
public:
  Digest()
  : context_(EVP_MD_CTX_new(), EVP_MD_CTX_free)
  {
    if (!context_ || EVP_DigestInit_ex(context_.get(), EVP_sha256(), nullptr) != 1) {
      throw std::runtime_error("grid digest initialization failed");
    }
  }

  void bytes(const void * data, size_t size)
  {
    if (EVP_DigestUpdate(context_.get(), data, size) != 1) {
      throw std::runtime_error("grid digest update failed");
    }
  }

  void little(uint64_t value, size_t size)
  {
    std::array<unsigned char, 8> encoded{};
    for (size_t i = 0; i < size; ++i) {
      encoded[i] = static_cast<unsigned char>(value >> (8 * i));
    }
    bytes(encoded.data(), size);
  }

  void real(double value)
  {
    uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    little(bits, sizeof(bits));  // Includes signed zero, independent of host byte order.
  }

  std::string finish()
  {
    std::array<unsigned char, EVP_MAX_MD_SIZE> result{};
    unsigned int size = 0;
    if (EVP_DigestFinal_ex(context_.get(), result.data(), &size) != 1 || size != 32) {
      throw std::runtime_error("grid digest finalization failed");
    }
    constexpr char digits[] = "0123456789abcdef";
    std::string hex;
    hex.reserve(64);
    for (size_t i = 0; i < size; ++i) {
      hex.push_back(digits[result[i] >> 4]);
      hex.push_back(digits[result[i] & 15]);
    }
    return hex;
  }

private:
  std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context_;
};
}  // namespace

bool Identity::same_original(const Identity & other) const
{
  // Digest covers ALL original geometry and raw cells, including floating bits.
  // Times are deliberately not part of the content digest, but are identity.
  return digest == other.digest && frame == other.frame && width == other.width &&
         height == other.height && resolution == other.resolution && origin == other.origin &&
         source_stamp_ns == other.source_stamp_ns && map_load_time_ns == other.map_load_time_ns;
}

Identity identify(const nav_msgs::msg::OccupancyGrid & grid)
{
  const auto & info = grid.info;
  const auto & p = info.origin.position;
  const auto & q = info.origin.orientation;
  Identity identity{"", grid.header.frame_id, info.width, info.height,
    static_cast<double>(info.resolution), {p.x, p.y, p.z, q.x, q.y, q.z, q.w},
    timestamp(grid.header.stamp), timestamp(info.map_load_time)};
  const uint64_t cells = static_cast<uint64_t>(info.width) * info.height;
  if (identity.frame != "map" || !info.width || !info.height || cells > kMaxOriginalCells ||
    grid.data.size() != cells || !std::isfinite(identity.resolution) || identity.resolution <= 0 ||
    !std::all_of(identity.origin.begin(), identity.origin.end(),
      [](double value) {return std::isfinite(value);}) ||
    p.z != 0 || q.x != 0 || q.y != 0 || q.z != 0 || (q.w != 1 && q.w != -1) ||
    identity.map_load_time_ns > identity.source_stamp_ns ||
    !std::all_of(grid.data.begin(), grid.data.end(),
      [](int8_t value) {return value >= -1 && value <= 100;}))
  {
    throw std::invalid_argument("unsupported original occupancy grid");
  }

  Digest digest;
  constexpr char magic[] = "ROSY-GRID-v1";
  digest.bytes(magic, sizeof(magic));  // The terminating zero is part of version 1.
  digest.little(identity.frame.size(), 4);
  digest.bytes(identity.frame.data(), identity.frame.size());
  digest.little(identity.width, 4);
  digest.little(identity.height, 4);
  digest.real(identity.resolution);
  for (double value : identity.origin) {digest.real(value);}
  digest.bytes(grid.data.data(), grid.data.size());  // Exact signed-int8 wire bits.
  identity.digest = digest.finish();
  return identity;
}
}  // namespace rosy_native_map
