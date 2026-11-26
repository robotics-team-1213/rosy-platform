---
surface: core
kind: additive
slug: native-omx-policy-lease
date: 2026-11-26
title: Native OMX policy lease ingress
---
A dedicated Fleet machine principal can read /api/v1/arm/lease-status and POST /api/v1/arm/lease-challenge for a native B target before lease delivery. A native grant includes the approved task scope and a one-use challenge pinned to the device session. HOLD confirmation requires an explicit response from the motor writer. Standard simulated targets retain their existing lease schema.
