# Fleet workcell observation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show two physical follower streams and three cameras inside ROSY's existing Cell screen, with collection and serving on Fleet PC and no developer tunnel dependency.

**Architecture:** A native ROS subscriber on Fleet PC sends source-bound arm snapshots to Fleet and JPEG frames through existing Vision ingestion. Fleet stays ROS-free, stores latest observations only, and serves them through normal authenticated reads. The existing Cell screen renders observations independently of the command compiler, owner or motion admission.

**Tech Stack:** Existing Python/FastAPI, ROS 2, Vision WebSocket protocol and static Console components; no new framework.

**Spec:** User's two followers, one wrist camera per follower, shared overhead camera, Fleet-owned runtime; reserved D-837 and API v1.295 will define the new observation boundary before product implementation.

## Global constraints

- Keep physical commands behind the existing CORE/OMX owner authority. No command publisher, torque write, serial access or owner activation in the observation bridge or Fleet.
- Explicit source manifest and separate producer credentials; never invent map/calibration records to register a preview camera.
- Joint topics stay under `/omx_commissioning/`; the three configured image topics are observation inputs.
- Original timestamps, process epoch and sequence survive transport. Server receipt time cannot refresh an old sample. Each source expires independently.
- Browser requests use the normal Fleet origin and viewer authentication. Producer secrets never reach the browser.
- Persistent native service and signed site image/configuration are deployment work; an SSH viewer, source tests or merged code alone do not prove deployed integration.

## Review focus

- Source credentials cannot publish as another arm/workcell; numeric and nonfinite data are rejected.
- Replay, restart epoch, backwards clock and interrupted transport do not produce fresh-looking old state.
- Cell command services being disabled does not disable read-only observations.
- Sign-out and credential changes remove displayed observations and late asynchronous responses.
- One disconnected source does not refresh or remove the other sources; browser disconnect expires visible values and decoded images.

## Task 1: Define and test Fleet observation boundary

- [x] Record D-837, source manifest, API v1.295 and producer/reader ownership; independent contract review.
- [x] Add committed RED tests for manifest identity, credentials, bounded latest cache, epoch/sequence/age checks and existing Fleet viewer auth.
- [x] Implement `fleet/server/site_observation/workcell_observations.py` and `workcell_observation_routes.py`; compose through existing CLI/app boundaries without ROS imports.
- [x] Add preview-only source registration to Fleet's existing preview source list and Vision's existing static credential intake, without sighting/map registration.
- [ ] Commit and run remote GREEN checks, installed resource/dependency checks and independent review; publish this boundary before dependent UI/runtime changes.

## Task 2: Native producer and existing Cell panel

- [x] Add committed RED tests for native source mapping, advancing sample transmission, original capture age and Vision wire encoding.
- [x] Implement a native ROS intake and user service using the explicit manifest. Reuse existing image encoding/Vision wire protocol, keep latest samples and bound transport queues.
- [x] Add an explicit persistent torque-OFF reader mode/service preserving current packet/model/fault/exclusive guards. Stop on torque/fault/ownership conflict without automatic re-entry; never loop the bounded observer. Define reader stop and verified bus release before any accepted owner handoff.
- [x] Add `operations/site_ui/console/cell/cell-observation.js` using current Fleet client, shared components and Vision leases; wire existing Cell session lifecycle and static allowlist.
- [x] Verify two arm panels and three images with real Chromium, source disconnects and logout; keep command controls unchanged. Fixture-backed images/API only; live deployment is Task 3.
- [ ] Commit, remotely verify, review and merge dependent implementation.

## Task 3: Deploy and prove the actual path

- [ ] Bind the two confirmed boards and three distinct camera selectors in private configuration; labels describe configuration, not accepted geometric pairing or calibration.
- [ ] Install producer credentials through existing protected host configuration and release pipeline; inspect exact installed image/source identities before starting.
- [ ] Run the native bridge and normal Fleet/Vision endpoints; verify actual joint samples and original frames through the ROSY Cell screen from its ordinary origin.
- [ ] Verify independent expiry by stopping one owned producer, then controlled recovery; demonstrate that developer SSH forwarding is unnecessary.
- [ ] Report source, deployment, observation and motion evidence separately. Do not claim grasping, calibration or physical motion acceptance from this work.
