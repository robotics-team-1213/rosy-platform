---
surface: fleet
kind: additive
slug: native-act-arm-lease-status
date: 2026-11-26
title: OMX native policy target status
---
GET /api/fleet/policy-approvals/targets/{workcell_id}/status verifies the TLS transport and native owner session separately. A fresh hardware_readback can report encoder positions, torque and motor errors during an exclusive B-arm commissioning session. The ready field indicates policy admission. This read-only operation neither opens an approval nor issues an arm command.
