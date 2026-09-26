#include "bno055_device.hpp"
#include "wiringPiI2C.h"
#include <cerrno>
#include <chrono>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <unistd.h>

namespace rosy_imu
{
namespace
{
void pause_ms(int ms) {std::this_thread::sleep_for(std::chrono::milliseconds(ms));}
std::string detail(const char *stage, int reg, int actual, int error)
{
  std::ostringstream out;
  out   << "stage=" << stage << " reg=0x" << std::hex << reg << std::dec
        << " actual=" << actual << " errno=" << error;
  return out.str();
}
}
Device::Device(std::string interface, Log log, std::function<bool()> running)
: interface_(std::move(interface)), log_(std::move(log)), running_(std::move(running))
{
  if (!log_) {
    log_ = [](const std::string &) {};
  }
  if (!running_) {
    running_ = [] {return true;};
  }
}
Device::~Device() {if (fd_ >= 0) {close(fd_);}}
void Device::initialize(bool reset_on_start)
{
  log_("stage=open bus=" + interface_ + " address=0x28");
  errno = 0;
  fd_ = wiringPiI2CSetupInterface(interface_.c_str(), 0x28);
  if (fd_ < 0) {throw std::runtime_error(detail("open", 0, fd_, errno));}
  errno = 0;
  int chip = wiringPiI2CReadReg8(fd_, 0);
  int error = errno;
  log_(detail("probe", 0, chip, error));
  if (chip != 0xA0) {
    throw std::runtime_error(detail("probe", 0, chip, error) +
        " BNO055 chip ID unavailable; refusing reset");
  }
  write_register(0x3D, 0, "config_mode");
  pause_ms(30);
  if (reset_on_start) {
    write_register(0x3F, 0x20, "reset");
        // Bosch requires at least 650 ms without I2C access after reset.
    log_("stage=reset_wait duration_ms=700");
    pause_ms(700);
  } else {
        // A process restart need not reset an already responsive sensor.
    log_("stage=reset_skipped reason=reset_on_start_false");
  }
  wait_register(0, 0xA0, "chip_boot", 2000);
  wait_register(0x3A, 0, "system_error_clear", 3000);
  write_register(0x3E, 0, "normal_power");
  pause_ms(500);
    // No-reset startup must not inherit units from a previous sensor owner.
    // Decode expects acceleration in m/s^2 and angular velocity in degrees/s.
  write_register(0x3B, 0, "units");
  write_register(0x3D, 8, "fusion_mode");
  pause_ms(30);
  wait_register(0x39, 5, "fusion_start", 5000);
  log_("stage=ready fusion=IMUPLUS");
}
void Device::write_register(int reg, int value, const char *stage)
{
  if (!running_()) {throw std::runtime_error("stage=shutdown initialization cancelled");}
  errno = 0;
  int result = wiringPiI2CWriteReg8(fd_, reg, value);
  int error = errno;
  if (result < 0) {throw std::runtime_error(detail(stage, reg, result, error));}
  log_(detail(stage, reg, value, 0));
}
void Device::wait_register(int reg, int expected, const char *stage, int timeout_ms)
{
  auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
  int last = -1, error = 0;
  while (running_() && std::chrono::steady_clock::now() < deadline) {
    errno = 0;
    last = wiringPiI2CReadReg8(fd_, reg);
    error = errno;
    if (last == expected) {log_(detail(stage, reg, last, error)); return;}
    pause_ms(100);
  }
  throw std::runtime_error(detail(stage, reg, last, error) + " BNO055 " + stage + " timed out");
}
int Device::read_register(int reg, const char *stage)
{
  errno = 0;
  int value = wiringPiI2CReadReg8(fd_, reg);
  int error = errno;
  if (value < 0) {throw std::runtime_error(detail(stage, reg, value, error));}
  return value;
}
std::array<uint8_t, 32> Device::read()
{
  std::array<uint8_t, 32> data{};
  errno = 0;
  int count = wiringPiI2CReadBlockData(fd_, 0x08, data.data(), data.size());
  int error = errno;
  if (count != static_cast<int>(data.size())) {
    throw std::runtime_error(detail("read", 0x08, count, error) +
        " BNO055 measurement read failed; no IMU sample published");
  }
  return data;
}
Health Device::health()
{
  Health value;
  value.temperature_c = static_cast<int8_t>(read_register(0x34, "health_temperature"));
  value.calibration = static_cast<uint8_t>(read_register(0x35, "health_calibration"));
  value.self_test = static_cast<uint8_t>(read_register(0x36, "health_self_test"));
  value.system_status = static_cast<uint8_t>(read_register(0x39, "health_system_status"));
  value.system_error = static_cast<uint8_t>(read_register(0x3A, "health_system_error"));
  return value;
}
}
