#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/range.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/u_int16_multi_array.hpp"
#include "sensor_msgs/msg/battery_state.hpp"
#include "realtime_tools/realtime_publisher.hpp"

#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>

#include "wiringPiI2C.h"

using realtime_tools::RealtimePublisher;

// ADC channel layout: 0..2 IR, 3 ultrasonic, 4 battery.
static constexpr int CH_IR_FIRST = 0;
static constexpr int CH_ULTRASONIC = 3;
static constexpr int CH_BATTERY = 4;
static constexpr int CH_COUNT = 5;

class RosySensorADC : public rclcpp::Node
{
    public:
        RosySensorADC() : Node("sensor_adc")
        {
            this->declare_parameter<std::string>("interface", "/dev/i2c-1");
            this->declare_parameter<double>("rate", 20.0);

            // PWR-001 duty cycling. core publishes power/mode; until a valid
            // message arrives the node keeps its full startup rate, so a core
            // outage can never leave the sensors slow.
            this->declare_parameter<double>("rate_active", 20.0);
            this->declare_parameter<double>("rate_idle", 5.0);
            this->declare_parameter<double>("rate_standby", 2.0);

            auto interface = this->get_parameter("interface").get_parameter_value().get<std::string>();

            fd_ = wiringPiI2CSetupInterface(interface.c_str(), 0x08);
            if (fd_ == -1) {
                // The C assert macro compiles out under NDEBUG; the external
                // supervisor owns restarts, so fail loudly and exit nonzero
                // (same rule as imu_bno055).
                RCLCPP_FATAL(this->get_logger(),
                             "Failed to init I2C communication on %s.", interface.c_str());
                throw std::runtime_error("sensor_adc: I2C init failed");
            }

            pub_us_sensor_ = this->create_publisher<sensor_msgs::msg::Range>("us_sensor/range", 10);
            pub_ir_sensor_ = this->create_publisher<std_msgs::msg::UInt16MultiArray>("ir_sensor/range", 10);
            pub_batt_state_ = this->create_publisher<sensor_msgs::msg::BatteryState>("batt_state", 10);
            // Latched health: late-joining consumers (CORE diagnostics) get
            // the last state immediately (imu_bno055 publishes the same
            // contract on sensors/imu/status).
            pub_health_ = this->create_publisher<std_msgs::msg::String>(
                "sensors/adc/status", rclcpp::QoS(1).transient_local());

            sub_power_mode_ = this->create_subscription<std_msgs::msg::String>(
                "power/mode", rclcpp::QoS(1).transient_local().reliable(),
                std::bind(&RosySensorADC::power_mode_callback, this, std::placeholders::_1));

            current_rate_ = this->get_parameter("rate").as_double();
            restart_timer(current_rate_);
            health_timer_ = this->create_wall_timer(std::chrono::seconds(1),
                std::bind(&RosySensorADC::health_callback, this));

            RCLCPP_INFO(this->get_logger(), "%s initialized...", this->get_name());
        }
        ~RosySensorADC() {}

    private:
        void restart_timer(double rate)
        {
            if(timer_) {
                timer_->cancel();
            }
            auto period = std::chrono::duration<double>(1.0 / rate);
            timer_ = this->create_wall_timer(period, std::bind(&RosySensorADC::timer_callback, this));
        }

        void power_mode_callback(const std_msgs::msg::String::SharedPtr msg)
        {
            double rate = current_rate_;
            bool standby = false;

            if(msg->data == "active") {
                rate = this->get_parameter("rate_active").as_double();
            } else if(msg->data == "idle") {
                rate = this->get_parameter("rate_idle").as_double();
            } else if(msg->data == "standby") {
                rate = this->get_parameter("rate_standby").as_double();
                standby = true;
            } else {
                // Unknown mode: keep the current rate rather than guessing.
                RCLCPP_WARN(this->get_logger(), "ignoring unknown power mode");
                return;
            }

            if(rate <= 0.0 || !std::isfinite(rate)) {
                RCLCPP_WARN(this->get_logger(), "ignoring non-positive rate for mode");
                return;
            }

            standby_ = standby;
            if(rate == current_rate_) {
                return;
            }

            current_rate_ = rate;
            restart_timer(rate);
            RCLCPP_INFO(this->get_logger(), "power mode '%s' -> %.1f Hz", msg->data.c_str(), rate);
        }

        // One channel round trip: write the register pointer, settle, read
        // the 12-bit sample. Both return codes are checked — a dead bus
        // yields short reads, not zeros.
        bool read_channel(int channel, uint16_t &value)
        {
            static constexpr uint8_t registers[CH_COUNT] = {0x88, 0xC8, 0x98, 0xD8, 0xF8};
            uint8_t data[2] = {0, };
            // wiringPiI2CRawWrite 가 const 를 받는 시그니처와 아닌 시그니처가
            // 공존한다 — 로컬 사본을 넘겨 어느 쪽에서도 컴파일되게 한다.
            uint8_t reg = registers[channel];

            const int written = wiringPiI2CRawWrite(fd_, &reg, 1);
            if (written < 1) {
                last_error_ = "ch" + std::to_string(channel) + ": write " + std::to_string(written);
                return false;
            }
            rclcpp::sleep_for(std::chrono::milliseconds(6));

            const int got = wiringPiI2CRawRead(fd_, data, 2);
            if (got != 2) {
                last_error_ = "ch" + std::to_string(channel) + ": read " + std::to_string(got);
                return false;
            }
            value = uint16_t(data[0] << 4) + uint16_t(data[1] >> 4);
            return true;
        }

        // True only when every channel of this cycle answered.
        bool read_cycle(int first, uint16_t adc_result[CH_COUNT])
        {
            for(int i = first; i < CH_COUNT; i++)
            {
                if(!read_channel(i, adc_result[i])) {
                    return false;
                }
            }
            return true;
        }

        void timer_callback()
        {
            uint16_t adc_result[CH_COUNT] = {0, 0, 0, 0, 0};

            // In standby only the wake sensor and the battery are worth the bus
            // time: two round trips per cycle instead of five.
            const int first = standby_ ? CH_ULTRASONIC : CH_IR_FIRST;

            // Fail-closed (imu pattern): a failed bus cycle publishes nothing.
            // CORE's freshness gate judges arrival, and zeroed samples through
            // a dead bus would look fresh while saying "no obstacle, full pack".
            if(!read_cycle(first, adc_result)) {
                consecutive_failures_++;
                RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 2000,
                                     "I2C cycle failed (%s); publishing nothing",
                                     last_error_.c_str());
                return;
            }
            consecutive_failures_ = 0;
            last_error_.clear();

            auto us_result = sensor_msgs::msg::Range();
            us_result.header.stamp = this->now();
            us_result.header.frame_id = "ultrasonic_link";
            us_result.radiation_type = sensor_msgs::msg::Range::ULTRASOUND;
            us_result.field_of_view = 0.26;
            us_result.min_range = 0.02;
            us_result.max_range = 3.0;
            us_result.range = 1.0 * (adc_result[CH_ULTRASONIC] / 4096.0) - 0.03;
            us_result.variance = 0;

            pub_us_sensor_->publish(us_result);


            if(!standby_)
            {
                auto ir_result = std_msgs::msg::UInt16MultiArray();
                ir_result.data.push_back(adc_result[2]);
                ir_result.data.push_back(adc_result[1]);
                ir_result.data.push_back(adc_result[0]);

                pub_ir_sensor_->publish(ir_result);
            }

            auto batt_result = sensor_msgs::msg::BatteryState();
            batt_result.header.stamp = this->now();
            batt_result.voltage = (adc_result[CH_BATTERY] / 4096.0) * 4.096 / (13.0 / 28.0);
            batt_result.temperature  = std::nan("");
            batt_result.current = std::nan("");
            batt_result.charge = std::nan("");
            batt_result.capacity = std::nan("");
            batt_result.design_capacity = 5.0;
            batt_result.percentage = std::nan("");
            batt_result.power_supply_status = sensor_msgs::msg::BatteryState::POWER_SUPPLY_STATUS_UNKNOWN;
            batt_result.power_supply_health = sensor_msgs::msg::BatteryState::POWER_SUPPLY_HEALTH_GOOD;
            batt_result.power_supply_technology = sensor_msgs::msg::BatteryState::POWER_SUPPLY_TECHNOLOGY_LION;
            batt_result.location = "base_link";
            batt_result.serial_number= "0";

            pub_batt_state_->publish(batt_result);
            RCLCPP_DEBUG(this->get_logger(), "%d %d %d %d %d", adc_result[0], adc_result[1], adc_result[2], adc_result[3], adc_result[4]);
        }

        void health_callback()
        {
            // Latched 1 Hz JSON health blob on sensors/adc/status.
            std::string error_json = last_error_.empty()
                ? std::string("null")
                : "\"" + last_error_ + "\"";
            char json[192];
            std::snprintf(json, sizeof(json),
                          "{\"ok\": %s, \"consecutive_failures\": %d, \"last_error\": %s, \"standby\": %s}",
                          consecutive_failures_ == 0 ? "true" : "false",
                          consecutive_failures_,
                          error_json.c_str(),
                          standby_ ? "true" : "false");
            auto msg = std_msgs::msg::String();
            msg.data = json;
            pub_health_->publish(msg);
        }

    private:
        int fd_;
        double current_rate_ = 20.0;
        bool standby_ = false;
        int consecutive_failures_ = 0;
        std::string last_error_;
        rclcpp::TimerBase::SharedPtr timer_;
        rclcpp::TimerBase::SharedPtr health_timer_;
        rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_power_mode_;
        rclcpp::Publisher<sensor_msgs::msg::Range>::SharedPtr pub_us_sensor_;
        rclcpp::Publisher<std_msgs::msg::UInt16MultiArray>::SharedPtr pub_ir_sensor_;
        rclcpp::Publisher<sensor_msgs::msg::BatteryState>::SharedPtr pub_batt_state_;
        rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_health_;
};


int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<RosySensorADC>());

    rclcpp::shutdown();
    return 0;
}