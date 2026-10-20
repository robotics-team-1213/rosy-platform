// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#ifndef ROSY_TEST__NATIVE_MAP_STATIC_FIXTURE_HPP_
#define ROSY_TEST__NATIVE_MAP_STATIC_FIXTURE_HPP_
#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <thread>
#include <gtest/gtest.h>
#include "interfaces/srv/map_adoption.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "nav2_costmap_2d/costmap_2d_ros.hpp"
#include "nav2_msgs/srv/clear_entire_costmap.hpp"
#include "rosy_native_map/static_layer.hpp"
#include "rosy_native_map/grid.hpp"
#include "std_srvs/srv/empty.hpp"
#include "tf2_ros/static_transform_broadcaster.h"

namespace rosy_native_map
{
// Read-only inspection of the genuine production plugin loaded by the real
// parent. No fake plugin, callback replacement, synthetic ACK or state writes.
struct StaticLayerTestAccess
{
  static uint64_t inputs(VerifiedStaticLayer & layer)
  {
    std::lock_guard<nav2_costmap_2d::Costmap2D::mutex_t> master(
      *layer.layered_costmap_->getCostmap()->getMutex());
    std::lock_guard<nav2_costmap_2d::Costmap2D::mutex_t> local(*layer.getMutex());
    return layer.native_input_count_;
  }
  static uint64_t process_calls(VerifiedStaticLayer & layer)
  {
    std::lock_guard<nav2_costmap_2d::Costmap2D::mutex_t> master(
      *layer.layered_costmap_->getCostmap()->getMutex());
    std::lock_guard<nav2_costmap_2d::Costmap2D::mutex_t> local(*layer.getMutex());
    return layer.native_process_count_;
  }
};
}  // namespace rosy_native_map

namespace static_fixture
{
using namespace std::chrono_literals;
using Grid = nav_msgs::msg::OccupancyGrid;
using Wire = interfaces::srv::MapAdoption;
using Costmap = nav2_costmap_2d::Costmap2D;
constexpr auto ACTIVE = lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE;
constexpr auto INACTIVE = lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE;
constexpr auto UNCONFIGURED = lifecycle_msgs::msg::State::PRIMARY_STATE_UNCONFIGURED;

class RosContext : public ::testing::Environment
{
public:
  void SetUp() override {rclcpp::init(0, nullptr);}
  void TearDown() override {rclcpp::shutdown();}
};
[[maybe_unused]] inline auto * context = ::testing::AddGlobalTestEnvironment(new RosContext());

inline Grid original()
{
  Grid value;
  value.header.frame_id = "map";
  value.header.stamp.nanosec = 20;
  value.info.map_load_time.nanosec = 10;
  value.info.width = 3; value.info.height = 2; value.info.resolution = .05F;
  value.info.origin.position.x = -1.25;
  value.info.origin.position.y = 2.5;
  value.info.origin.orientation.w = 1.;
  value.data = {-1, 0, 1, 49, 100, -1};
  return value;
}

template<typename Predicate> void await(Predicate predicate)
{
  const auto end = std::chrono::steady_clock::now() + 8s;
  while (!predicate()) {
    if (std::chrono::steady_clock::now() >= end) {throw std::runtime_error("native static condition timed out");}
    std::this_thread::sleep_for(10ms);
  }
}

class InspectParent : public nav2_costmap_2d::Costmap2DROS
{
public:
  using Costmap2DROS::Costmap2DROS;
  rclcpp::CallbackGroup::SharedPtr private_group() {return callback_group_;}
  void release_failed_configuration()
  {
    // FAILURE returns to UNCONFIGURED but native resources already exist.
    // The lifecycle cleanup transition is unavailable there. Run the genuine
    // parent resource cleanup before its class loader/member destruction.
    nav2_costmap_2d::Costmap2DROS::on_cleanup(rclcpp_lifecycle::State());
  }
  void pause_and_quiesce()
  {
    pause();  // The real SDK's stop_updates_ is atomic.
    std::lock_guard<std::mutex> cycle(_dynamic_parameter_mutex);
    // All previous updateMap work has left this native mutex; later cycles
    // observe stop_updates_, so controlled full/partial applications cannot race.
  }
};

class Harness
{
public:
  explicit Harness(bool latched = false, const std::vector<rclcpp::Parameter> & extras = {},
    bool expect_configured = true)
  {
    ns = "/native_static_test_" + std::to_string(++serial_);
    control = std::make_shared<rclcpp::Node>("static_observer", ns);
    publisher = control->create_publisher<Grid>("map", rclcpp::QoS(1).reliable().transient_local());
    transforms = std::make_unique<tf2_ros::StaticTransformBroadcaster>(control);
    const auto base = "static_test_base_" + std::to_string(serial_);
    geometry_msgs::msg::TransformStamped transform;
    transform.header.stamp = control->now();
    transform.header.frame_id = "map"; transform.child_frame_id = base;
    transform.transform.translation.x = -1.2; transform.transform.translation.y = 2.55;
    transform.transform.rotation.w = 1.;
    transforms->sendTransform(transform);
    parent = std::make_shared<InspectParent>("global_costmap", ns, "global_costmap", false);
    executor.add_node(control); executor.add_node(parent->get_node_base_interface());
    const std::vector<rclcpp::Parameter> parameters{
      {"plugins", std::vector<std::string>{"static_layer"}},
      {"static_layer.plugin", "rosy_native_map::VerifiedStaticLayer"},
      {"map_topic", ns + "/map"}, {"global_frame", "map"}, {"robot_base_frame", base},
      {"update_frequency", 20.}, {"publish_frequency", 0.}, {"initial_transform_timeout", 2.},
      {"track_unknown_space", true}, {"use_maximum", false},
      {"static_layer.enabled", true}, {"static_layer.footprint_clearing_enabled", false},
      {"static_layer.subscribe_to_updates", false}, {"static_layer.map_subscribe_transient_local", true}};
    auto set = [&](const rclcpp::Parameter & parameter) {
        if (!parent->has_parameter(parameter.get_name())) {
          parent->declare_parameter(parameter.get_name(), parameter.get_parameter_value());
        } else if (!parent->set_parameter(parameter).successful) {
          throw std::runtime_error("fixture parameter rejected before configuration");
        }
      };
    for (const auto & parameter : parameters) {set(parameter);}
    for (const auto & parameter : extras) {set(parameter);}
    if (latched) {publisher->publish(original());}
    const auto state = parent->configure().id();
    // Rejected plugin configuration returns immediately after the parent's
    // independent TF listener thread is created. Require a genuine callback
    // before its teardown; cancelling before spin starts can strand the join.
    await([&] {return parent->getTfBuffer()->canTransform("map", base, tf2::TimePointZero);});
    if (!expect_configured) {return;}
    if (state != INACTIVE) {throw std::runtime_error("actual costmap parent configuration failed");}
    layer = std::dynamic_pointer_cast<rosy_native_map::VerifiedStaticLayer>(
      parent->getLayeredCostmap()->getPlugins()->at(0));
    if (!layer) {throw std::runtime_error("real production plugin was not loaded");}
    client = control->create_client<Wire>(ns + "/global_costmap/static_layer/map_adoption");
    if (!client->wait_for_service(8s)) {throw std::runtime_error("actual static readback missing");}
    if (latched) {await([&] {return inputs() >= 1;});}
  }
  ~Harness()
  {
    layer.reset();
    if (parent->get_current_state().id() == ACTIVE) {parent->deactivate();}
    if (parent->get_current_state().id() == INACTIVE) {parent->cleanup();}
    else if (parent->getLayeredCostmap()) {parent->release_failed_configuration();}
    executor.remove_node(parent->get_node_base_interface()); executor.remove_node(control);
  }
  uint64_t inputs() {return rosy_native_map::StaticLayerTestAccess::inputs(*layer);}
  void publish(const Grid & value)
  {
    await([&] {return publisher->get_subscription_count() > 0;});
    const auto count = inputs(); publisher->publish(value);
    await([&] {return inputs() > count;});
  }
  template<typename Service> typename Service::Response request(
    const typename rclcpp::Client<Service>::SharedPtr & endpoint,
    const typename Service::Request::SharedPtr & value)
  {
    auto future = endpoint->async_send_request(value);
    if (executor.spin_until_future_complete(future, 8s) != rclcpp::FutureReturnCode::SUCCESS) {
      throw std::runtime_error("native DDS request timed out");
    }
    return *future.get();
  }
  Wire::Response read()
  {
    auto value = std::make_shared<Wire::Request>(); value->challenge.fill(++nonce_);
    auto response = request<Wire>(client, value);
    if (response.challenge != value->challenge) {throw std::runtime_error("challenge mismatch");}
    return response;
  }
  Wire::Response activate()
  {
    if (parent->activate().id() != ACTIVE) {throw std::runtime_error("real costmap activation failed");}
    Wire::Response positive;
    await([&] {positive = read(); return positive.adopted;});
    return positive;
  }
  std::vector<unsigned char> cells(bool master = false)
  {
    std::lock_guard<Costmap::mutex_t> top(*parent->getCostmap()->getMutex());
    std::lock_guard<Costmap::mutex_t> local(*layer->getMutex());
    auto * grid = master ? parent->getCostmap() : static_cast<Costmap *>(layer.get());
    return {grid->getCharMap(), grid->getCharMap() + grid->getSizeInCellsX() * grid->getSizeInCellsY()};
  }
  void bounds()
  {
    double min_x = 1e9, min_y = 1e9, max_x = -1e9, max_y = -1e9;
    layer->updateBounds(-1.2, 2.55, 0., &min_x, &min_y, &max_x, &max_y);
  }
  void apply(bool full = true, bool with_bounds = true)
  {
    std::lock_guard<Costmap::mutex_t> top(*parent->getCostmap()->getMutex());
    if (with_bounds) {bounds();}
    layer->updateCosts(*parent->getCostmap(), 0, 0, full ? 3 : 2, full ? 2 : 1);
  }
  void reset()
  {
    std::lock_guard<Costmap::mutex_t> top(*parent->getCostmap()->getMutex());
    parent->resetLayers();
  }
  rclcpp::executors::SingleThreadedExecutor executor;
  std::string ns;
  rclcpp::Node::SharedPtr control;
  rclcpp::Publisher<Grid>::SharedPtr publisher;
  std::unique_ptr<tf2_ros::StaticTransformBroadcaster> transforms;
  std::shared_ptr<InspectParent> parent;
  std::shared_ptr<rosy_native_map::VerifiedStaticLayer> layer;
  rclcpp::Client<Wire>::SharedPtr client;
private:
  inline static int serial_{0};
  uint8_t nonce_{0};
};
inline const std::vector<unsigned char> expected{255, 0, 0, 0, 254, 255};
}  // namespace static_fixture
#endif  // ROSY_TEST__NATIVE_MAP_STATIC_FIXTURE_HPP_
