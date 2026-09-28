#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/jazzy/setup.bash
source /opt/rosy_ws/install/setup.bash

exec "$@"
