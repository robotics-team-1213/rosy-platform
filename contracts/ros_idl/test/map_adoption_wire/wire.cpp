// Copyright 2026 ROSY contributors
// SPDX-License-Identifier: Apache-2.0
#include <iostream>
#include <stdexcept>

#include "interfaces/srv/map_adoption.hpp"
#include "rclcpp/serialization.hpp"
#include "rclcpp/serialized_message.hpp"

template<typename Message>
Message round_trip(const Message & input)
{
  rclcpp::Serialization<Message> codec;
  rclcpp::SerializedMessage bytes;
  codec.serialize_message(&input, &bytes);
  Message output;
  codec.deserialize_message(&bytes, &output);
  return output;
}

int main()
{
  using Service = interfaces::srv::MapAdoption;
  Service::Request request;
  for (size_t i = 0; i < request.challenge.size(); ++i) {
    request.challenge[i] = static_cast<uint8_t>(i + 1);
  }
  if (round_trip(request).challenge != request.challenge) {
    throw std::runtime_error("request challenge changed during serialization");
  }
  Service::Response response;
  response.contract_version = Service::Response::CONTRACT_VERSION;
  response.challenge = request.challenge;
  response.reason = "wire_fixture_not_native_adoption";
  // This fixture must never resemble positive consumer-adoption evidence.
  response.active = false;
  response.adopted = false;
  const auto copy = round_trip(response);
  if (copy != response || copy.contract_version != 1 || copy.adopted || copy.active) {
    throw std::runtime_error("response serialization mismatch");
  }
  std::cout << "native_map_wire_cpp: request and closed response round trips passed\n";
}
