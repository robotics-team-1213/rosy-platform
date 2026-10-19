// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include "native_map_static_fixture.hpp"
using namespace static_fixture;

TEST(NativeMapStatic, InactiveBufferedOriginalIsNotAppliedEvidence)
{
  Harness run;
  EXPECT_FALSE(run.read().adopted);
  run.publish(original());
  const auto reply = run.read();
  EXPECT_FALSE(reply.active); EXPECT_FALSE(reply.adopted);
  EXPECT_EQ(reply.grid_digest, rosy_native_map::identify(original()).digest);
  EXPECT_EQ(run.cells(), expected);
  EXPECT_EQ(rosy_native_map::StaticLayerTestAccess::process_calls(*run.layer), 1U);
}

TEST(NativeMapStatic, LatchedOriginalAppliesThroughTheActualParent)
{
  Harness run(true);
  const auto reply = run.activate();
  EXPECT_TRUE(reply.active); EXPECT_TRUE(reply.adopted);
  EXPECT_EQ(reply.contract_version, 1); EXPECT_EQ(reply.role, "static_layer");
  EXPECT_EQ(reply.node_fqn, run.parent->get_fully_qualified_name());
  EXPECT_EQ(reply.node_fqn, run.ns + "/global_costmap/global_costmap");
  EXPECT_EQ(reply.grid_digest, rosy_native_map::identify(original()).digest);
  EXPECT_EQ(reply.source_stamp_ns, 20U); EXPECT_EQ(reply.map_load_time_ns, 10U);
  EXPECT_EQ(reply.width, 3U); EXPECT_EQ(reply.height, 2U);
  EXPECT_EQ(reply.build_id.size(), 64U); EXPECT_EQ(reply.config_digest.size(), 64U);
  EXPECT_EQ(run.cells(true), expected);
}

TEST(NativeMapStatic, FreshBoundsAndFullWindowAreRequiredAfterReset)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce(); run.reset();
  const auto pending = run.read();
  EXPECT_FALSE(pending.adopted); EXPECT_GT(pending.generation, before.generation);
  run.apply(true, false);
  EXPECT_FALSE(run.read().adopted);
  run.apply(false);
  EXPECT_TRUE(run.layer->isCurrent());  // Native current=true is still insufficient.
  EXPECT_FALSE(run.read().adopted);
  EXPECT_EQ(run.cells(true), (std::vector<unsigned char>{255, 0, 255, 255, 255, 255}));
  run.apply(); const auto after = run.read();
  EXPECT_TRUE(after.adopted); EXPECT_GT(after.generation, pending.generation);
  EXPECT_EQ(run.cells(true), expected);
}

TEST(NativeMapStatic, ExactRepeatCannotRenewGenerationOrReprocessOriginal)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce(); run.publish(original());
  const auto after = run.read();
  EXPECT_TRUE(after.adopted); EXPECT_EQ(after.generation, before.generation);
  EXPECT_EQ(after.instance_id, before.instance_id);
  EXPECT_EQ(rosy_native_map::StaticLayerTestAccess::process_calls(*run.layer), 1U);
}

TEST(NativeMapStatic, EqualConvertedDifferentRawRetiresBeforeNativeMutation)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce(); auto changed = original(); changed.data[2] = 49;
  run.publish(changed); const auto after = run.read();
  EXPECT_FALSE(after.adopted); EXPECT_GT(after.generation, before.generation);
  EXPECT_EQ(after.grid_digest, before.grid_digest);
  EXPECT_EQ(run.cells(), expected);
  EXPECT_EQ(rosy_native_map::StaticLayerTestAccess::process_calls(*run.layer), 1U);
  run.publish(original()); run.apply(); EXPECT_FALSE(run.read().adopted);
}

TEST(NativeMapStatic, OriginalTimeChangeRetiresEvenWithTheSameContentDigest)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce(); auto changed = original(); ++changed.header.stamp.nanosec;
  run.publish(changed); const auto after = run.read();
  EXPECT_FALSE(after.adopted); EXPECT_GT(after.generation, before.generation);
  EXPECT_EQ(after.grid_digest, before.grid_digest);
  EXPECT_EQ(rosy_native_map::StaticLayerTestAccess::process_calls(*run.layer), 1U);
}

TEST(NativeMapStatic, RealClearEntireServiceRequiresANewFullApplicationGeneration)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce();
  using Clear = nav2_msgs::srv::ClearEntireCostmap;
  auto clear = run.control->create_client<Clear>(
    run.ns + "/global_costmap/clear_entirely_global_costmap");
  ASSERT_TRUE(clear->wait_for_service(8s));
  run.request<Clear>(clear, std::make_shared<Clear::Request>());
  const auto pending = run.read();
  EXPECT_FALSE(pending.adopted); EXPECT_GT(pending.generation, before.generation);
  run.apply(); const auto after = run.read();
  EXPECT_TRUE(after.adopted); EXPECT_GT(after.generation, pending.generation);
  EXPECT_EQ(after.instance_id, before.instance_id); EXPECT_EQ(run.cells(true), expected);
}

TEST(NativeMapStatic, ExternalMasterResizePermanentlyRetiresTheOriginalInstance)
{
  Harness run(true); const auto before = run.activate();
  run.parent->pause_and_quiesce();
  run.parent->getLayeredCostmap()->resizeMap(4, 2, .05F, -1.25, 2.5, true);
  const auto after = run.read();
  EXPECT_FALSE(after.adopted); EXPECT_GT(after.generation, before.generation);
  run.publish(original()); EXPECT_FALSE(run.read().adopted);
}

TEST(NativeMapStatic, MixedParameterTransactionHasNoInheritedSideEffects)
{
  Harness run(true); const auto before = run.activate();
  const auto result = run.parent->set_parameters_atomically({
      rclcpp::Parameter("static_layer.enabled", false), rclcpp::Parameter("lethal_cost_threshold", 50)});
  EXPECT_FALSE(result.successful); EXPECT_TRUE(run.layer->isEnabled());
  EXPECT_TRUE(run.parent->get_parameter("static_layer.enabled").as_bool());
  EXPECT_EQ(run.parent->get_parameter("lethal_cost_threshold").as_int(), 100);
  EXPECT_EQ(run.read().config_digest, before.config_digest); EXPECT_EQ(run.cells(), expected);
}

TEST(NativeMapStatic, UnsupportedInitialProfilesCannotConfigureThePlugin)
{
  const std::vector<rclcpp::Parameter> rejected{
    {"static_layer.enabled", false}, {"rolling_window", true}, {"use_maximum", true},
    {"static_layer.subscribe_to_updates", true}, {"static_layer.map_subscribe_transient_local", false},
    {"static_layer.footprint_clearing_enabled", true}, {"lethal_cost_threshold", 0},
    {"unknown_cost_value", 99}};
  for (const auto & parameter : rejected) {
    Harness run(false, {parameter}, false);
    ASSERT_EQ(run.parent->get_current_state().id(), UNCONFIGURED) << parameter.get_name();
    std::weak_ptr<nav2_costmap_2d::Layer> rejected_layer =
      run.parent->getLayeredCostmap()->getPlugins()->at(0);
    run.parent->release_failed_configuration();
    EXPECT_EQ(run.parent->getLayeredCostmap(), nullptr);
    EXPECT_TRUE(rejected_layer.expired());
  }
}

TEST(NativeMapStatic, ActualFootprintTopicDoesNotClearTheRetainedStaticCells)
{
  Harness run(true); const auto before = run.activate(); run.parent->pause_and_quiesce();
  auto publisher = run.control->create_publisher<geometry_msgs::msg::Polygon>(
    run.ns + "/global_costmap/footprint", rclcpp::QoS(1));
  await([&] {return publisher->get_subscription_count() > 0;});
  geometry_msgs::msg::Polygon triangle; triangle.points.resize(3);
  triangle.points[0].x = -.2F; triangle.points[1].x = .2F; triangle.points[2].y = .2F;
  publisher->publish(triangle);
  await([&] {run.executor.spin_some(); return run.parent->getRobotFootprint().size() == 3;});
  EXPECT_EQ(run.cells(), expected); EXPECT_EQ(run.read().generation, before.generation);
  EXPECT_TRUE(run.read().adopted);  // This is not geometry acceptance.
}

TEST(NativeMapStatic, ParentCleanupJoinsInflightCallbacksBeforePluginDestruction)
{
  Harness run(true); run.activate(); run.parent->deactivate();
  EXPECT_FALSE(run.read().adopted);
  struct Barrier
  {
    std::promise<void> entered, released;
    std::shared_future<void> gate{released.get_future().share()};
    std::atomic<bool> finished{false};
    std::once_flag once;
    void release() {std::call_once(once, [&] {released.set_value();});}
  };
  auto barrier = std::make_shared<Barrier>();
  struct Release {std::shared_ptr<Barrier> barrier; ~Release() {barrier->release();}} release{barrier};
  auto service = run.parent->create_service<std_srvs::srv::Empty>(
    "~/test_inflight", [barrier](std_srvs::srv::Empty::Request::SharedPtr,
      std_srvs::srv::Empty::Response::SharedPtr) {
      barrier->entered.set_value(); barrier->gate.wait(); barrier->finished.store(true);
    }, rclcpp::ServicesQoS(), run.parent->private_group());
  auto probe = run.control->create_client<std_srvs::srv::Empty>(
    run.ns + "/global_costmap/global_costmap/test_inflight");
  ASSERT_TRUE(probe->wait_for_service(8s)); auto entered = barrier->entered.get_future();
  auto flight = probe->async_send_request(std::make_shared<std_srvs::srv::Empty::Request>());
  ASSERT_EQ(entered.wait_for(8s), std::future_status::ready);
  auto queued = run.client->async_send_request(std::make_shared<Wire::Request>());
  std::weak_ptr<rosy_native_map::VerifiedStaticLayer> weak = run.layer; run.layer.reset();
  auto cleanup = std::async(std::launch::async, [&] {return run.parent->cleanup().id();});
  EXPECT_EQ(cleanup.wait_for(100ms), std::future_status::timeout); EXPECT_FALSE(weak.expired());
  barrier->release(); ASSERT_EQ(cleanup.wait_for(8s), std::future_status::ready);
  EXPECT_EQ(cleanup.get(), UNCONFIGURED); EXPECT_TRUE(barrier->finished.load()); EXPECT_TRUE(weak.expired());
  run.client->remove_pending_request(queued); probe->remove_pending_request(flight);
}

TEST(NativeMapStatic, FreshPluginObjectGetsADifferentInstanceIdentity)
{
  std::array<uint8_t, 16> before;
  {Harness run(true); before = run.activate().instance_id;}
  Harness fresh(true); EXPECT_NE(before, fresh.activate().instance_id);
}

TEST(NativeMapStatic, RealNativeNontrinaryAndUnknownConversionMatchesTheOriginal)
{
  {Harness run(true, {{"trinary_costmap", false}}); run.activate();
    EXPECT_EQ(run.cells(), (std::vector<unsigned char>{255, 0, 2, 124, 254, 255}));
    EXPECT_EQ(run.cells(true), run.cells());}
  {Harness run(true, {{"track_unknown_space", false}}); run.activate();
    EXPECT_EQ(run.cells(true), (std::vector<unsigned char>{0, 0, 0, 0, 254, 0}));}
}
