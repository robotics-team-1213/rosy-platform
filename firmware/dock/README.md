# Rosy Charging Dock — Agent Contract

- **Document ID:** ROSY-DOCK-001
- **Status:** Contract accepted; firmware reference implementation in `firmware/`
- **Related:** ADR D-28, `docs/plans/2026-09-02-docking-station-design.md`,
  `src/rosy_core/rosy_core/docking/agent.py`, `test/test_dock_contract.py`

## Why the dock has a controller

Not to report current. **To avoid energising bare contacts.**

A charging dock sits on the floor with exposed DC contacts at pet and toddler
height. Held permanently live, they are a short-circuit and foreign-object
hazard: dropped keys, spilled water, a curious hand. So the dock detects a load
before it energises anything, and de-energises the moment the load leaves.

That requires a microcontroller regardless of what the robot wants to know. Once
one is there, measuring the current and serving it over the network costs almost
nothing — and it solves a separate problem the robot cannot solve on its own.

## Why the robot cannot answer "am I charging?"

`rosy_sensor_adc` publishes `batt_state` with `current`, `temperature` and
`percentage` as NaN and `power_supply_status` hardcoded to `UNKNOWN`. There is
no current sensor on the robot, so the strongest confirmation Nav2's docking
framework offers (`use_battery_status`) is unavailable, and the weakest (a
distance threshold) proves neither contact nor conduction.

The dock measures instead. This keeps the robot hardware untouched and turns an
inference into an electrical fact.

## Direction: the robot polls

**The dock never initiates a connection.**

The dock does not know which robot is approaching. The robot knows exactly which
dock it is going to — the address is in its dock database. An inbound path into
the robot's API would be one more unauthenticated surface for no gain, and
routing through Fleet would mean a robot cannot charge when Fleet is down.

Polling runs only during a docking sequence and while docked, so it costs
nothing on a robot going about its work.

## `GET /status`

```json
{
  "dock_id": "dock_1",
  "firmware": "1.0.0",
  "output_enabled": true,
  "load_present": true,
  "charging": true,
  "current_a": 1.42,
  "output_voltage_v": 8.31,
  "faults": []
}
```

| Field | Required | Meaning |
|---|---|---|
| `load_present` | **yes** | A load is detected across the contacts |
| `charging` | **yes** | Current is actually flowing into that load |
| `current_a` | no | Measured charge current, amps |
| `output_voltage_v` | no | Measured output voltage, volts |
| `output_enabled` | no | Whether the dock has energised its contacts |
| `dock_id` | no | Identity, for an operator staring at two docks |
| `firmware` | no | Version, for the same reason |
| `faults` | no | List of strings; empty when healthy |

### `load_present` and `charging` are different questions

Contacts can be engaged while no current flows — an oxidised contact, a full
pack, a protection board that has latched. Reporting them separately is what
lets the robot tell "I am parked in a dock that is not charging me" from "I
never made contact", and those need different recoveries: the first is a fault
to report, the second is an approach to retry.

Collapsing them into one boolean makes that distinction unavailable to the state
machine, which is why both are required rather than defaulted.

### Missing required fields are an error, not a default

The client treats an absent `load_present` or `charging` as a bad response.
Filling them in with `false` would merge "not charging" with "did not say", and
the robot's retry strategy depends on telling those apart.

## The robot does not trust this endpoint alone

Reporting `"charging": true` does not by itself convince the robot it is
charging. Confirmation requires the dock's current **and** the robot's own
filtered pack voltage not falling over a window.

The reason is what that confirmation feeds: it suppresses the D-27 deep-discharge
shutdown. A device on the LAN able to assert `charging: true` would otherwise be
able to switch off a safety path, and the consequence of believing it is a robot
sitting still on a pack that keeps draining.

Do not treat this as distrust of your firmware. It is a property the system needs
to hold even when the dock is faulty, mis-wired, or replaced by something else at
the same address.

## Electrical

- **Pack:** 2S lithium-ion, 8.4 V full, ~5 Ah. Charge CC/CV to 8.4 V.
- **Termination** is the charger's job. The pack's protection board is the last
  line of defence and must not be relied on for normal termination.
- **Contacts:** spring-loaded pins in the dock against flat pads on the robot.
  Pins in the dock because the dock is serviceable without opening the robot,
  and the sprung side wears first.
- **Robot side** is contacts plus reverse-polarity protection — no active parts.

## Mechanical

The robot docks **forwards**. Its IR array and ultrasonic sensor both face `+X`,
so driving in forwards keeps the alignment sensors pointed at the dock for the
whole approach; rear docking would need sensors the robot does not have.

A funnel with sloped side walls converts a lateral error of a centimetre or two
into a correct final position, and wide pads tolerate the rest. Every docking
system leans on this. A controller that has to be millimetre-accurate on its own
is a controller that fails on a dusty floor.

## Network

The dock joins the site WLAN as a station. **Credentials are not compiled in** —
they are provisioned at setup and stored in NVS, and `test_dock_contract.py`
fails the build if a credential appears in the sources.

The endpoint is plain HTTP on the local network. It serves one read-only route
and takes no commands, so there is nothing for an attacker to actuate; the
confidentiality of "how many amps is this dock delivering" does not justify
certificate management on a microcontroller. If the dock ever gains a command
surface, that judgement has to be revisited.

## Firmware

`firmware/rosy_dock/rosy_dock.ino` is the reference implementation. The rules it
must keep, in order of importance:

1. Never energise the output without a detected load.
2. De-energise on load removal, on fault, and on boot.
3. Serve `/status` with at least `load_present` and `charging`.
4. Answer quickly — the robot polls inside a control tick and times out.
