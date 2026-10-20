// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include <algorithm>
#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include <gtest/gtest.h>
#include "interfaces/srv/map_adoption.hpp"
#include "lifecycle_msgs/msg/state.hpp"
#include "rosy_native_map/amcl.hpp"
#include "rosy_native_map/grid.hpp"
#include "rosy_native_map/support.hpp"
#include "std_srvs/srv/empty.hpp"

using namespace std::chrono_literals;
namespace
{
using Grid = nav_msgs::msg::OccupancyGrid;
using Wire = interfaces::srv::MapAdoption;

class RosContext : public ::testing::Environment
{
public:
  void SetUp() override {rclcpp::init(0, nullptr);}
  void TearDown() override {rclcpp::shutdown();}
};
[[maybe_unused]] auto * ros_context = ::testing::AddGlobalTestEnvironment(new RosContext());

struct CallbackBarrier
{
  std::promise<void> entered;
  std::promise<void> released;
  std::shared_future<void> gate{released.get_future().share()};
  std::atomic<bool> finished{false};
  std::once_flag release_once;
  void release() {std::call_once(release_once, [&] {released.set_value();});}
};

struct ReleaseOnExit
{
  std::shared_ptr<CallbackBarrier> barrier;
  ~ReleaseOnExit() {barrier->release();}
};

class InspectAmcl : public rosy_native_map::VerifiedAmcl
{
public:
  using VerifiedAmcl::VerifiedAmcl;
  uint64_t inputs()
  {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return native_input_count_;
  }
  uint64_t native_calls()
  {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return native_handle_count_;
  }
  std::vector<int> cells()
  {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    std::vector<int> result;
    if (map_ && map_->cells) {
      for (int i = 0; i < map_->size_x * map_->size_y; ++i) {
        result.push_back(map_->cells[i].occ_state);
      }
    }
    return result;
  }
  void install_inflight_probe(const std::shared_ptr<CallbackBarrier> & barrier)
  {
    // Real DDS callback on the actual owned group; no fake map/adoption owner.
    probe_ = create_service<std_srvs::srv::Empty>(
      "~/test_inflight", [barrier](std_srvs::srv::Empty::Request::SharedPtr,
        std_srvs::srv::Empty::Response::SharedPtr) {
        barrier->entered.set_value();
        barrier->gate.wait();
        barrier->finished.store(true);
      }, rmw_qos_profile_services_default, callback_group_);
  }

private:
  rclcpp::Service<std_srvs::srv::Empty>::SharedPtr probe_;
};

Grid original()
{
  Grid value;
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

template<typename Predicate>
void await(Predicate predicate)
{
  const auto end = std::chrono::steady_clock::now() + 8s;
  while (!predicate()) {
    if (std::chrono::steady_clock::now() >= end) {
      throw std::runtime_error("actual AMCL/DDS condition timed out");
    }
    std::this_thread::sleep_for(10ms);
  }
}

class Harness
{
public:
  explicit Harness(bool first_only = false, bool latched = false)
  {
    const auto ns = "/native_map_test_" + std::to_string(++serial_);
    control = std::make_shared<rclcpp::Node>("wire_observer", ns);
    publisher = control->create_publisher<Grid>(
      "map", rclcpp::QoS(1).reliable().transient_local());
    if (latched) {publisher->publish(original());}
    rclcpp::NodeOptions options;
    options.arguments({"--ros-args", "-r", "__ns:=" + ns});
    options.parameter_overrides({rclcpp::Parameter("first_map_only", first_only)});
    amcl = std::make_shared<InspectAmcl>(options);
    if (amcl->configure().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE ||
      amcl->activate().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE)
    {
      throw std::runtime_error("real AMCL configure/activation failed");
    }
    executor.add_node(control);
    client = control->create_client<Wire>(ns + "/amcl/map_adoption");
    if (!client->wait_for_service(8s)) {throw std::runtime_error("no actual readback service");}
    if (latched) {await([&] {return amcl->inputs() >= 1;});}
  }

  ~Harness()
  {
    if (amcl) {
      if (amcl->get_current_state().id() == lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE) {
        amcl->deactivate();
      }
      if (amcl->get_current_state().id() == lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE) {
        amcl->cleanup();
      }
      amcl.reset();
    }
    executor.remove_node(control);
  }

  void publish(const Grid & value)
  {
    await([&] {return publisher->get_subscription_count() > 0;});
    const auto before = amcl->inputs();
    publisher->publish(value);
    await([&] {return amcl->inputs() > before;});
  }

  Wire::Response read()
  {
    auto request = std::make_shared<Wire::Request>();
    request->challenge.fill(++challenge_);
    auto future = client->async_send_request(request);
    if (executor.spin_until_future_complete(future, 8s) != rclcpp::FutureReturnCode::SUCCESS) {
      throw std::runtime_error("actual readback query timed out");
    }
    auto response = *future.get();
    if (response.challenge != request->challenge) {throw std::runtime_error("wrong challenge");}
    return response;
  }

  std::shared_ptr<InspectAmcl> amcl;
  rclcpp::Node::SharedPtr control;
  rclcpp::Publisher<Grid>::SharedPtr publisher;
  rclcpp::Client<Wire>::SharedPtr client;
  rclcpp::executors::SingleThreadedExecutor executor;

private:
  static int serial_;
  uint8_t challenge_{0};
};
int Harness::serial_ = 0;
}  // namespace

TEST(NativeMapAmcl, MissingMapStaysClosed)
{
  Harness run;
  const auto response = run.read();
  EXPECT_FALSE(response.adopted);
  EXPECT_TRUE(run.amcl->cells().empty());
  EXPECT_EQ(run.amcl->native_calls(), 0U);
}

TEST(NativeMapAmcl, LatchedOriginalIsProcessedByTheRealNativeConsumer)
{
  Harness run(false, true);
  const auto response = run.read();
  EXPECT_TRUE(response.active);
  EXPECT_TRUE(response.adopted);
  EXPECT_EQ(response.contract_version, 1);
  EXPECT_EQ(response.role, "amcl");
  EXPECT_EQ(response.node_fqn, run.amcl->get_fully_qualified_name());
  EXPECT_EQ(response.grid_digest, rosy_native_map::identify(original()).digest);
  EXPECT_EQ(response.source_stamp_ns, 20U);
  EXPECT_EQ(response.map_load_time_ns, 10U);
  EXPECT_EQ(response.width, 3U);
  EXPECT_EQ(response.height, 2U);
  EXPECT_EQ(response.build_id.size(), 64U);
  EXPECT_EQ(response.config_digest.size(), 64U);
  EXPECT_TRUE(std::any_of(response.instance_id.begin(), response.instance_id.end(),
    [](uint8_t value) {return value != 0;}));
  EXPECT_EQ(run.amcl->native_calls(), 1U);
  EXPECT_EQ(run.amcl->cells(), (std::vector<int>{0, -1, 0, 0, 1, 0}));
}

TEST(NativeMapAmcl, ExactRepeatNeverReprocessesOrRenewsGeneration)
{
  Harness run;
  run.publish(original());
  const auto before = run.read();
  ASSERT_TRUE(before.adopted);
  run.publish(original());
  const auto after = run.read();
  EXPECT_TRUE(after.adopted);
  EXPECT_EQ(after.generation, before.generation);
  EXPECT_EQ(after.instance_id, before.instance_id);
  EXPECT_EQ(run.amcl->native_calls(), 1U);
}

TEST(NativeMapAmcl, EqualConvertedRawChangeRetiresBothFirstMapModesBeforeMutation)
{
  for (const bool first_only : {false, true}) {
    Harness run(first_only);
    run.publish(original());
    const auto before = run.read();
    ASSERT_TRUE(before.adopted);
    auto changed = original(); changed.data[2] = 49;
    run.publish(changed);
    const auto after = run.read();
    EXPECT_FALSE(after.adopted);
    EXPECT_GT(after.generation, before.generation);
    EXPECT_EQ(run.amcl->native_calls(), 1U);
    EXPECT_EQ(run.amcl->cells(), (std::vector<int>{0, -1, 0, 0, 1, 0}));
    run.publish(original());
    EXPECT_FALSE(run.read().adopted);
    EXPECT_EQ(run.amcl->native_calls(), 1U);
  }
}

TEST(NativeMapAmcl, TimeOnlyOriginalChangeRetiresWithoutReprocessing)
{
  Harness run;
  run.publish(original());
  ASSERT_TRUE(run.read().adopted);
  auto changed = original(); ++changed.header.stamp.nanosec;
  run.publish(changed);
  EXPECT_FALSE(run.read().adopted);
  EXPECT_EQ(run.amcl->native_calls(), 1U);
}

TEST(NativeMapAmcl, MixedParametersAreRejectedBeforeInheritedEffects)
{
  Harness run;
  run.publish(original());
  ASSERT_TRUE(run.read().adopted);
  const auto alpha = run.amcl->get_parameter("alpha1").as_double();
  const auto topic = run.amcl->get_parameter("map_topic").as_string();
  const auto result = run.amcl->set_parameters_atomically({
      rclcpp::Parameter("map_topic", "other_map"), rclcpp::Parameter("alpha1", alpha + .1)});
  EXPECT_FALSE(result.successful);
  EXPECT_EQ(run.amcl->get_parameter("alpha1").as_double(), alpha);
  EXPECT_EQ(run.amcl->get_parameter("map_topic").as_string(), topic);
  EXPECT_TRUE(run.read().adopted);
  EXPECT_EQ(run.amcl->native_calls(), 1U);
}

TEST(NativeMapAmcl, DeactivateCleanupCannotReviveAndRecreationChangesInstance)
{
  std::array<uint8_t, 16> previous;
  {
    Harness run;
    run.publish(original());
    previous = run.read().instance_id;
    run.amcl->deactivate();
    EXPECT_FALSE(run.read().adopted);
    EXPECT_NE(run.amcl->activate().id(), lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE);
    EXPECT_EQ(run.amcl->cleanup().id(), lifecycle_msgs::msg::State::PRIMARY_STATE_UNCONFIGURED);
    EXPECT_NE(run.amcl->configure().id(), lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE);
  }
  Harness fresh;
  fresh.publish(original());
  const auto response = fresh.read();
  EXPECT_TRUE(response.adopted);
  EXPECT_NE(response.instance_id, previous);
}

TEST(NativeMapAmcl, QueuedRealCallbacksAreQuiescedBeforeCleanup)
{
  Harness run;
  run.publish(original());
  ASSERT_TRUE(run.read().adopted);
  auto barrier = std::make_shared<CallbackBarrier>();
  ReleaseOnExit release{barrier};
  run.amcl->install_inflight_probe(barrier);
  auto probe = run.control->create_client<std_srvs::srv::Empty>(
    std::string(run.amcl->get_fully_qualified_name()) + "/test_inflight");
  ASSERT_TRUE(probe->wait_for_service(8s));
  auto entered = barrier->entered.get_future();
  auto in_flight = probe->async_send_request(std::make_shared<std_srvs::srv::Empty::Request>());
  ASSERT_EQ(entered.wait_for(8s), std::future_status::ready);
  // The owned private executor is now demonstrably inside an actual callback.
  // Keep a genuine production readback queued behind it during cleanup.
  auto pending = run.client->async_send_request(std::make_shared<Wire::Request>());
  run.amcl->deactivate();
  auto cleanup = std::async(std::launch::async, [&] {return run.amcl->cleanup().id();});
  EXPECT_EQ(cleanup.wait_for(100ms), std::future_status::timeout);
  EXPECT_FALSE(barrier->finished.load());
  barrier->release();
  ASSERT_EQ(cleanup.wait_for(8s), std::future_status::ready);
  EXPECT_EQ(cleanup.get(), lifecycle_msgs::msg::State::PRIMARY_STATE_UNCONFIGURED);
  EXPECT_TRUE(barrier->finished.load());
  EXPECT_TRUE(run.amcl->cells().empty());
  run.client->remove_pending_request(pending);
  probe->remove_pending_request(in_flight);
}

TEST(NativeMapAmcl, RejectsConcurrentVerifiedInstancesInOneProcess)
{
  Harness run;
  EXPECT_THROW(std::make_shared<InspectAmcl>(rclcpp::NodeOptions()), std::runtime_error);
}

TEST(NativeMapAmcl, ConfigDigestPreservesTypedPrecisionAndArrayBoundaries)
{
  auto node = std::make_shared<rclcpp_lifecycle::LifecycleNode>("native_config_identity");
  node->declare_parameter("near_double", .2);
  auto before = rosy_native_map::parameter_digest(*node, "/map");
  node->set_parameter(rclcpp::Parameter("near_double", .20000001));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/map"));
  node->declare_parameter("wide_integer", static_cast<int64_t>(1) << 40);
  before = rosy_native_map::parameter_digest(*node, "/map");
  node->set_parameter(rclcpp::Parameter("wide_integer", (static_cast<int64_t>(1) << 40) + 1));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/map"));
  node->declare_parameter("reals", std::vector<double>{.2, -.0});
  before = rosy_native_map::parameter_digest(*node, "/map");
  node->set_parameter(rclcpp::Parameter("reals", std::vector<double>{.20000001, -.0}));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/map"));
  before = rosy_native_map::parameter_digest(*node, "/map");
  node->set_parameter(rclcpp::Parameter("reals", std::vector<double>{.20000001, .0}));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/map"));
  node->declare_parameter("strings", std::vector<std::string>{"a", "bc"});
  before = rosy_native_map::parameter_digest(*node, "/map");
  node->set_parameter(rclcpp::Parameter("strings", std::vector<std::string>{"ab", "c"}));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/map"));
  before = rosy_native_map::parameter_digest(*node, "/map");
  EXPECT_EQ(before, rosy_native_map::parameter_digest(*node, "/map"));
  EXPECT_NE(before, rosy_native_map::parameter_digest(*node, "/other_map"));
}
