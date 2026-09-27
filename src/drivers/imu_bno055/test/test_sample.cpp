#include "../src/imu_sample.hpp"
#include <iostream>

int main()
{
  std::array<uint8_t, 32> bytes{};
  bytes[25] = 0x40;   // identity quaternion
  bytes[4] = 0xd5; bytes[5] = 3;   // gravity 9.81 m/s2
  bytes[12] = 0xf0; bytes[13] = 0xff;   // signed -1 degree/s
  auto sample = rosy_imu::decode(bytes);
  if (std::abs(sample.acceleration[2] - 9.81) > 1e-9 ||
    sample.angular_velocity[0] != -1.0 || sample.quaternion[3] != 1.0)
  {
    return 1;
  }
  bytes.fill(0);
  try {
    rosy_imu::decode(bytes); return 2;
  } catch (const std::runtime_error &) {
  }
  bytes[25] = 0x7f;
  try {
    rosy_imu::decode(bytes); return 3;
  } catch (const std::runtime_error &) {
  }
  std::cout << "signed units and invalid quaternion checks passed\n";
  return 0;
}
