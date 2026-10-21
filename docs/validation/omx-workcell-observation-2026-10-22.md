# OMX workcell observation verification — 2026-10-22

The intended runtime is the Fleet PC: native torque-OFF readers → native ROS
subscriber → authenticated Fleet/Vision → the existing `/console/cell` screen.
The developer workstation is only a client. CORE/OMX command ownership remains
separate from this display-only path.

## Verified source and test evidence

| Revision | Check | Result and limit |
|---|---|---|
| `ada14033b9` | Shared protocol and architecture | 86 passed; no host activation |
| `e676d0f425` | Contract pre-push | 519 fast + 21,723 affected passed; 1,171 skipped |
| `e03b746015` | Fleet intake, auth, CLI and architecture | 182 passed; one measured-size failure corrected at `c527bca693` (40 architecture passed) |
| `6eab9fae00` | Fleet deployment environment defaults | 92 passed |
| `c25dce219d` | Vision manifest, CLI, pairing, architecture | 101 passed |
| `1f312a0a48` | Vision deployment environment defaults | 86 passed |
| `0615263626` | Actual Cell page in Chromium and browser scope | 11 passed using API/JPEG fixtures |
| `fe2765d67a` | Signed deployment, updater, firewall, preflight, architecture | 278 passed, 2 skipped |
| `6aebb15368` | Native bridge, reader, register probe, architecture, documents | 110 passed after actual YAML and external-shutdown regressions |
| `896fc5e4df` | Combined Fleet/Vision/native/Cell checks with Chromium enabled | 182 passed; Console size-unit failure corrected at `4a11450c36` (40 architecture passed) |
| `7c967f44ec` | Actual verified HTTPS/WSS transport pipeline | 1 passed: native arm POST, viewer 401/authenticated GET, camera ingest, Fleet preview lease and actual Vision frame read |
| `363de80103` | Missing-header admission, AI role restrictions, Cell asset ownership, transport, architecture | 96 passed after full publication checks identified two integration regressions |

The earlier station-camera lifespan timeout did not recur in focused reruns or
the broad `e676d0f425` run. Its original renewal-worker delay remains unexplained.
Later publication runs failed different station variants: ordinary-work
completion in `d6692a3706`, and `CHARGE_MOTION_READBACK_UNAVAILABLE` in the
`09bdd9c9b6` shutdown-CHARGING variant. The latter traceback shows the inner
one-second return-renewal deadline expiring while FastAPI waits for a sync
dependency worker. Host contention is plausible, but not demonstrated. No
station safety deadline, production behavior, or failure allowlist was changed.
The same publication run found the missing-header/Cell-asset regressions above
and fixture-reference secret-scan findings; these require final-head checks
before publication. No failed head is presented as green.
The HTTPS/WSS transport test exercises actual servers independently of the
fixture-backed browser checks. Its arm values and JPEG are test inputs, rather
than physical device samples. Websockets 17 reports a connection-context
deprecation warning; the test closes the connection and both servers.

## Fleet PC observations

- The previously verified bounded diagnostic run received two six-joint streams
  and three camera images simultaneously, with torque OFF. One reader later
  received an external stop request; its caller is unknown. This does not prove
  a disconnected arm or a persistent installation.
- Three native camera services were active during this review. Wrist cameras
  share a USB serial string, so distinct stable USB port paths identify them.
- A new five-second bounded read at source `09bdd9c9b6` received 49 Arm A and
  17 Arm B samples, each containing six motors, torque OFF and zero hardware
  errors; both readers exited successfully. A separate five-second ROS image
  check received 50 frames from each of the three cameras, all 640×480 BGR8,
  with maximum observed capture ages of approximately 3/3/4 milliseconds. These checks were
  separate, rather than one simultaneous end-to-end run. Readers stopped
  after the bounded check; no persistent service was activated.
- The isolated native Python 3.14.4 environment imports system ROS, OpenCV,
  canonical protocol modules, websockets 17.0.1 and Dynamixel SDK 3.8.4.
- Both new native service units pass `systemd-analyze --user verify`. A warning
  belongs to an unrelated pre-existing desktop unit.
- The Fleet PC's Docker Compose renders the new overlay with public placeholder
  inputs and confirms separate read-only role mounts. This does not verify the
  protected production environment file, which requires OS authentication.

## Deployment and acceptance still required

1. Merge reviewed source and build, sign and verify a new site candidate. Existing
   Fleet/Vision images predate the new observation APIs and source registration.
2. Install the private manifest and five distinct source credentials with the
   role-isolated overlay; bind the native services to immutable source and the
   actual site CA. Do not modify files inside an already signed candidate.
3. Start the two passive readers and native bridge on Fleet PC, then verify actual
   arm samples and camera frames through authenticated normal-origin Cell reads.
4. Stop one owned producer, verify independent expiry, and verify controlled
   recovery without SSH forwarding or a separate diagnostic page.

No live integrated Cell display, installed persistent operation, accepted joint
calibration, learned-policy execution, torque ON, grasp or physical motion is
established by the checks above. A command owner handoff first stops the passive
readers and verifies that their serial FDs and buses are released.
