#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>

namespace rosy_imu
{
struct Sample
{
  std::array<double, 3> acceleration;
    // Preserve the driver contract: degrees/s, converted by consumers.
  std::array<double, 3> angular_velocity;
  std::array<double, 4> quaternion;   // x, y, z, w
};
inline Sample decode(const std::array<uint8_t, 32> & data)
{
  auto word = [&data](unsigned offset) {
      int v = data[offset] | (static_cast<int>(data[offset + 1]) << 8);
      return v >= 0x8000 ? v - 0x10000 : v;
    };
  Sample result{};
  for (unsigned axis = 0; axis < 3; ++axis) {
    result.acceleration[axis] = word(axis * 2) / 100.0;
    result.angular_velocity[axis] = word(12 + axis * 2) / 16.0;
  }
  result.quaternion = {word(26) / 16384.0, word(28) / 16384.0,
    word(30) / 16384.0, word(24) / 16384.0};
  double norm = 0;
  for (double v : result.quaternion) {
    norm += v * v;
  }
  if (!std::isfinite(norm) || norm < .81 || norm > 1.21) {
    throw std::runtime_error("stage=decode BNO055 invalid orientation; no IMU sample published");
  }
  return result;
}
}
