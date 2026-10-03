#include "bno055_device.hpp"
#include "imu_sample.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/imu.hpp"
#include "std_msgs/msg/string.hpp"
#include "realtime_tools/realtime_publisher.hpp"
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <stdexcept>

// ROS owns scheduling/reporting; Device owns I2C and Sample owns decoding.
class RosyIMUBNO055 : public rclcpp::Node {
public:
  RosyIMUBNO055()
  : Node("imu_bno055")
  {
    auto interface = declare_parameter<std::string>("interface", "/dev/i2c-0");
    frame_id_ = declare_parameter<std::string>("frame_id", "imu_link");
    double rate = declare_parameter<double>("rate", 100.0);
    bool reset_on_start = declare_parameter<bool>("reset_on_start", false);
    double orientation_stddev = declare_parameter<double>("orientation_stddev_rad", 0.0);
    double angular_velocity_stddev = declare_parameter<double>(
      "angular_velocity_stddev_deg_s", 0.0);
    double linear_acceleration_stddev = declare_parameter<double>(
      "linear_acceleration_stddev_mps2", 0.0);
    if (!std::isfinite(rate) || rate <= 0 || rate > 100) {
      throw std::runtime_error("stage=config IMU rate must be in (0, 100] Hz");
    }
    orientation_covariance_ = covariance(orientation_stddev, "orientation_stddev_rad");
    angular_velocity_covariance_ = covariance(
      angular_velocity_stddev, "angular_velocity_stddev_deg_s");
    linear_acceleration_covariance_ = covariance(
      linear_acceleration_stddev, "linear_acceleration_stddev_mps2");
    auto pub = create_publisher<sensor_msgs::msg::Imu>("imu_raw", rclcpp::SystemDefaultsQoS());
    imu_pub_ = std::make_shared<realtime_tools::RealtimePublisher<sensor_msgs::msg::Imu>>(pub);
    health_pub_ = create_publisher<std_msgs::msg::String>("sensors/imu/status",
      rclcpp::QoS(1).transient_local());
    device_ = std::make_unique<rosy_imu::Device>(interface,
        [this](const std::string & line) {RCLCPP_INFO(get_logger(), "%s", line.c_str());},
        [] {return rclcpp::ok();});
    device_->initialize(reset_on_start);
    timer_ = create_wall_timer(std::chrono::duration<double>(1.0 / rate),
                                  std::bind(&RosyIMUBNO055::tick, this));
    health_timer_ = create_wall_timer(std::chrono::seconds(1),
                                         std::bind(&RosyIMUBNO055::report_health, this));
  }

private:
  void tick()
  {
    rosy_imu::Sample sample;
    try {sample = rosy_imu::decode(device_->read());} catch (const std::exception & exc) {
      ++read_errors_;
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000, "%s", exc.what());
      return;
    }
    if (!imu_pub_->trylock()) {return;}
    auto & msg = imu_pub_->msg_;
    msg.header.stamp = now();
    msg.header.frame_id = frame_id_;
    msg.orientation.x = sample.quaternion[0];
    msg.orientation.y = sample.quaternion[1];
    msg.orientation.z = sample.quaternion[2];
    msg.orientation.w = sample.quaternion[3];
    msg.angular_velocity.x = sample.angular_velocity[0];
    msg.angular_velocity.y = sample.angular_velocity[1];
    msg.angular_velocity.z = sample.angular_velocity[2];
    msg.linear_acceleration.x = sample.acceleration[0];
    msg.linear_acceleration.y = sample.acceleration[1];
    msg.linear_acceleration.z = sample.acceleration[2];
    msg.orientation_covariance = orientation_covariance_;
    msg.angular_velocity_covariance = angular_velocity_covariance_;
    msg.linear_acceleration_covariance = linear_acceleration_covariance_;
    imu_pub_->unlockAndPublish();
    read_errors_ = 0;
    last_good_ = std::chrono::steady_clock::now();
    if (++samples_ == 1) {RCLCPP_INFO(get_logger(), "stage=stream first_valid_sample=true");}
  }
  void report_health()
  {
    bool fresh = samples_ > 0 &&
      std::chrono::steady_clock::now() - last_good_ < std::chrono::milliseconds(500);
    rosy_imu::Health health;
    bool register_valid = false;
    try {
      health = device_->health();
      register_valid = health.system_status == 5 && health.system_error == 0 &&
        (health.self_test & 0x0f) == 0x0f;
      health_read_errors_ = 0;
    } catch (const std::exception & exc) {
      ++health_read_errors_;
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000, "%s", exc.what());
    }
    const auto system_calibration = (health.calibration >> 6) & 0x03;
    const auto gyro_calibration = (health.calibration >> 4) & 0x03;
    const auto accel_calibration = (health.calibration >> 2) & 0x03;
    const auto mag_calibration = health.calibration & 0x03;
    std_msgs::msg::String msg;
    msg.data = std::string("{\"valid\":") + (fresh && register_valid ? "true" : "false") +
      ",\"samples\":" + std::to_string(samples_) +
      ",\"consecutive_read_errors\":" + std::to_string(read_errors_) +
      ",\"health_read_errors\":" + std::to_string(health_read_errors_) +
      ",\"system_calibration\":" + std::to_string(system_calibration) +
      ",\"gyro_calibration\":" + std::to_string(gyro_calibration) +
      ",\"accel_calibration\":" + std::to_string(accel_calibration) +
      ",\"mag_calibration\":" + std::to_string(mag_calibration) +
      ",\"self_test\":" + std::to_string(health.self_test) +
      ",\"system_status\":" + std::to_string(health.system_status) +
      ",\"system_error\":" + std::to_string(health.system_error) +
      ",\"temperature_c\":" + std::to_string(health.temperature_c) + "}";
    health_pub_->publish(msg);
  }
  static std::array<double, 9> covariance(double stddev, const char *name)
  {
    if (!std::isfinite(stddev) || stddev < 0) {
      throw std::runtime_error(std::string("stage=config ") + name +
        " must be finite and non-negative");
    }
    // ROS Imu: reported data with unknown covariance remains all-zero.
    std::array<double, 9> result{};
    if (stddev > 0) {
      double variance = stddev * stddev;
      result[0] = variance;
      result[4] = variance;
      result[8] = variance;
    }
    return result;
  }
  std::string frame_id_;
  std::unique_ptr<rosy_imu::Device> device_;
  std::shared_ptr<realtime_tools::RealtimePublisher<sensor_msgs::msg::Imu>> imu_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr health_pub_;
  rclcpp::TimerBase::SharedPtr timer_, health_timer_;
  std::chrono::steady_clock::time_point last_good_{};
  std::array<double, 9> orientation_covariance_{};
  std::array<double, 9> angular_velocity_covariance_{};
  std::array<double, 9> linear_acceleration_covariance_{};
  uint64_t samples_ = 0, read_errors_ = 0, health_read_errors_ = 0;
};
int main(int argc, char *argv[])
{
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<RosyIMUBNO055>());
  } catch (const std::exception & exc) {
    RCLCPP_ERROR(rclcpp::get_logger("imu_bno055"), "%s", exc.what());
    if (rclcpp::ok()) {rclcpp::shutdown();}
    return 1;
  }
  if (rclcpp::ok()) {rclcpp::shutdown();}
  return 0;
}
