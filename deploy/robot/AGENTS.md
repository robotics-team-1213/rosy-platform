<!-- Parent: ../AGENTS.md -->
<!-- Updated: 2026-09-28 -->

# Robot product deployments

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Group deployment inputs by robot product. This directory does not own shared
robot behavior, ROS interfaces, or final device commands; those remain in
`src/` and the product-local device owners.

## Products

| Directory | Purpose | Acceptance boundary |
|-----------|---------|---------------------|
| `pinky_pro/` | Pinky Pro runtime, image, release, SD media, and development compatibility files | Product image and physical device gates are tracked separately |
| `omx/` | OMX workstation development and simulation preparation (see `omx/AGENTS.md`) | No field runtime or actuator authority is accepted by this directory move |

## Rules

- Keep product-specific deployment inputs under that product's directory.
- Put genuinely shared ROS contracts and runtime behavior under `src/` only
  after their producers, consumers, and deployment closure are demonstrated.
- A source path move does not change ROS package identity, installed paths,
  image contents, or hardware acceptance.

<!-- MANUAL: -->
