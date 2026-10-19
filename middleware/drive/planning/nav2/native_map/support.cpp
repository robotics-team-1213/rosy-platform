// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include "rosy_native_map/support.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <stdexcept>
#include <openssl/evp.h>
#include <openssl/rand.h>

namespace rosy_native_map
{
namespace {std::atomic<bool> amcl_owned{false};}

StandaloneLease::StandaloneLease()
{
  if (amcl_owned.exchange(true)) {
    throw std::runtime_error("verified AMCL requires standalone ownership");
  }
}
StandaloneLease::~StandaloneLease() {amcl_owned.store(false);}

std::array<uint8_t, 16> new_instance_id()
{
  std::array<uint8_t, 16> id{};
  if (RAND_bytes(id.data(), id.size()) != 1 ||
    std::all_of(id.begin(), id.end(), [](uint8_t value) {return value == 0;}))
  {
    throw std::runtime_error("native instance entropy unavailable");
  }
  id[6] = (id[6] & 15) | 64;
  id[8] = (id[8] & 63) | 128;
  return id;
}

std::string sha256(const std::string & bytes)
{
  std::array<unsigned char, EVP_MAX_MD_SIZE> result{};
  unsigned int size = 0;
  if (EVP_Digest(bytes.data(), bytes.size(), result.data(), &size, EVP_sha256(), nullptr) != 1 ||
    size != 32)
  {
    throw std::runtime_error("native configuration hash failed");
  }
  constexpr char digits[] = "0123456789abcdef";
  std::string hex;
  for (size_t i = 0; i < size; ++i) {
    hex.push_back(digits[result[i] >> 4]);
    hex.push_back(digits[result[i] & 15]);
  }
  return hex;
}

std::string parameter_digest(rclcpp_lifecycle::LifecycleNode & node, const std::string & topic)
{
  auto names = node.list_parameters({}, 0).names;
  std::sort(names.begin(), names.end());
  std::string bytes = "ROSY-MAP-CONFIG-v1:";
  auto integer = [&](uint64_t value) {
      for (size_t i = 0; i < 8; ++i) {bytes.push_back(static_cast<char>(value >> (i * 8)));}
    };
  auto real = [&](double value) {
      uint64_t bits;
      std::memcpy(&bits, &value, sizeof(bits));
      integer(bits);
    };
  auto append = [&](const std::string & value) {
      integer(value.size());
      bytes.append(value);
    };
  append(topic);  // Actual resolved subscription includes remapping, not only map_topic text.
  for (const auto & name : names) {
    const auto value = node.get_parameter(name).to_parameter_msg().value;
    append(name);
    bytes.push_back(static_cast<char>(value.type));
    // Exact typed ParameterValue bytes. Display formatting loses double/int64
    // precision and cannot be a configuration identity.
    switch (value.type) {
      case 0: break;  // PARAMETER_NOT_SET has no value.
      case 1: bytes.push_back(value.bool_value ? 1 : 0); break;
      case 2: integer(static_cast<uint64_t>(value.integer_value)); break;
      case 3: real(value.double_value); break;
      case 4: append(value.string_value); break;
      case 5:
        integer(value.byte_array_value.size());
        for (auto item : value.byte_array_value) {bytes.push_back(static_cast<char>(item));}
        break;
      case 6:
        integer(value.bool_array_value.size());
        for (bool item : value.bool_array_value) {bytes.push_back(item ? 1 : 0);}
        break;
      case 7:
        integer(value.integer_array_value.size());
        for (auto item : value.integer_array_value) {integer(static_cast<uint64_t>(item));}
        break;
      case 8:
        integer(value.double_array_value.size());
        for (double item : value.double_array_value) {real(item);}
        break;
      case 9:
        integer(value.string_array_value.size());
        for (const auto & item : value.string_array_value) {append(item);}
        break;
      default: throw std::runtime_error("unsupported native parameter type");
    }
  }
  return sha256(bytes);
}
}  // namespace rosy_native_map
