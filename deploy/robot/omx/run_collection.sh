#!/usr/bin/env bash
set -e
: "${ROSY_OMX_COLLECTION_ROOT:?immutable source root required}"
: "${ROSY_ROS_SETUP:?accepted ROS setup required}"
: "${ROSY_OMX_OVERLAY_SETUP:?accepted native overlay setup required}"
: "${ROS_DOMAIN_ID:?explicit accepted domain required}"
: "${ROSY_COLLECTION_PROFILE:?private measured profile required}"
: "${ROSY_COLLECTION_TEACHER:?private accepted teacher required}"
: "${ROSY_COLLECTION_ACCEPTANCE:?field acceptance receipt required}"
: "${ROSY_COLLECTION_OUTPUT:?new raw session directory required}"
source "$ROSY_ROS_SETUP"
source "$ROSY_OMX_OVERLAY_SETUP"
# No-cross-host DDS: collection runs on the controller/camera host only.
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_STATIC_PEERS=
exec python3 "$ROSY_OMX_COLLECTION_ROOT/deploy/robot/omx/collection_cli.py" collect \
  --profile "$ROSY_COLLECTION_PROFILE" --teacher "$ROSY_COLLECTION_TEACHER" \
  --acceptance "$ROSY_COLLECTION_ACCEPTANCE" --out "$ROSY_COLLECTION_OUTPUT" \
  --episodes "${ROSY_COLLECTION_EPISODES:-1}"
