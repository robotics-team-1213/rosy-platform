# 16. ROSY Interface Design Principles

## 1. Purpose

ROSY exposes state and control through several human-facing surfaces. They serve
different people, answer different questions, and must not look or behave alike.

This document fixes what every surface shares and what each surface is free to
invent. It binds regardless of framework: the rules below are about evidence,
colour, hierarchy and vocabulary, not about a rendering stack.

## 2. Surfaces

| Surface | Audience | Question it answers | v1 status |
|---|---|---|---|
| Robot console | field operator | "Can I send this robot now?" | live (`core` `/dashboard` only — D-77) |
| Device runtime | installer, maintainer | "Is this hardware standing up correctly?" | live (`/dashboard` host and ROS-graph panels) |
| Fleet | dispatcher | "Which robot is the problem?" | live (`fleet` console) |
| Robot face | bystander | "What is it about to do?" | live (`rosy_emotion` LCD, `info_screen`) |
| Control diagnostic | control-stack maintainer | "What is the absorbed IO graph showing?" | live on legacy `control/launch/robot.launch.py` only; not composed with CORE |
| Game host | laptop match operator | "Are the pitch, ball, robots, and goals visible?" | live localhost preview in `rosy_games` (D-101); never CORE `/dashboard` |

The robot face is a user interface. It is the only surface for people who never
open a browser, and the only one with no input.

## 3. The Five Laws

These hold on every surface. A surface that breaks one is wrong, not different.

### Law 0 — A surface states only what the robot knows

D-32 established that a hollow endpoint returns an honest 501 rather than a
lying 200. Interfaces inherit that. A value with no source is not rendered as
`0`. A control the robot cannot honour is not rendered as a button.

### Law 1 — Colour carries meaning, never decoration

Three closed sets, never mixed (§6). Decorative gradients, ambient textures and
per-metric tinting spend the colour budget that a threshold alarm needs.

### Law 2 — Surface is hierarchy

Things that report sit flat. Things that change the world are raised. Grouping
is done by ground and rule, not by giving every block the same outline. An
operator learns "raised means it moves" once, and it holds everywhere.

### Law 3 — Irreversible actions differ in kind, not degree

An action that cannot be undone from the same screen — emergency stop, release
rollback, map reset, undock — is a different visual category, not a red variant
of an ordinary button.

### Law 4 — Vocabulary belongs to the audience

Labels are the plain language of whoever reads that surface. For an operator
that means Korean plain words. For an installer reading the ROS graph,
`DOMAIN ID` and `DDS ISOLATION` are plain words and stay. Consistency means each
surface speaks its own audience's plain language, not that all surfaces share
one wording.

## 4. Three Layers

What is shared is law, measure, and the browser controls that draw that law.
Layout stays with the surface.

| Layer | Content | Scope |
|---|---|---|
| L1 — Law | colour, type, space, radius, evidence states, hierarchy | binding on every surface |
| L1.5 — Headless state | framework-free accessors over server-judged evidence | shared behaviour, no paint |
| L2 — Grammar | where a control sits, and the question the surface answers | per surface |
| L3 — Content | what a capability contributes | portable across surfaces |

Browser chrome is one set (D-194) in `web_common`: `ui-text`, `ui-head`,
`ui-grid`, `ui-button`, `ui-field`, `ui-tag`, `ui-chip`, `ui-triage`, and
`ui-evidence`. A button names a `kind`. Evidence names a `state`. A surface
places the control and does not repaint it. A new page copies
`web_common/template.html`: a `ui-shell` with one `grammar` and a `ui-topbar`. The robot face stays a pixel
renderer and does not mount these elements (D-75). The four pieces D-92 left
undesigned as components — irreversible confirm, fleet exception row, narrow
console, face intent — stay undesigned until a second surface needs the logic.

### Binding instruments

A law that has no test is still prose. These are the instruments:

| Law | Instrument | Gate |
|---|---|---|
| Colour means something | `tokens.css` only. A copied hex matches that file. Pitch hex lives in one `:root`. Raster hex matches the PNG pipeline | `test_shared_controls.py`, `test_map_raster_color_contract.py` |
| Type is a closed scale | `--text-micro` through `--text-display` | `test_shared_controls.py` |
| Measure is a closed scale | padding, margin, gap use `--space-*`. Radius uses `--radius-*`. A 1px rule is a line, not a step | `test_shared_controls.py` |
| Irreversible is a kind | `ui-button` `kind="irreversible"`. Surfaces do not repaint it | `test_shared_controls.py` |
| Hierarchy is the surface | flat ground reports, raised ground acts. Names are `--surface-flat` and `--surface-raised` | token file. Diagnostic grounds use those hex values |
| Evidence is four states | `fresh`, `delayed`, `disconnected`, `unavailable`. The server judges. Stale text is quiet, not a status colour | `test_shared_controls.py` |
| Vocabulary is the audience's | Korean plain words for an operator. Graph names stay for an installer | not a token. Review, not a test |
| The frame fits the grammar | no-scroll surfaces do not scroll *and do not crush* at their declared viewport; lists scroll inside the frame; safety actions are always in view (D-201) | `test_dashboard_browser.py`, `test_fleet_console_browser.py`, `test_games_board_browser.py` (opt-in) |
| Danger is a fill | status-crit is never a text colour; any warm-coloured text is ≥ 4.5:1 against its effective ground (D-202) | `test_fleet_console_browser.py` (opt-in) |
| The rendered scale is closed | every visible computed font-size is a token step — not just the declared ones (D-203) | `test_dashboard_browser.py` (opt-in) |
| Text keeps a contrast floor | every visible text is ≥ 4.5:1 (≥ 3:1 at display size) against its effective ground, on every surface incl. off-token ones — selection never spends readability (D-214) | `test_dashboard_browser.py`, `test_fleet_console_browser.py` (opt-in) |
| Confirmation is native | world-changing actions pass `window.confirm`; decline makes zero calls; `alert`/`prompt` are not surface vocabulary (D-218) | `test_web_dialog_contract.py` |
| The summary is exception-pinned | console triage categories and fleet queues are closed declarative tables; empty means absent, never green (D-219) | `test_triage_contract.py`, `src/site/fleet/test/test_console_queues_contract.py` |
| The surfaces are still | no element transitions or animates; state changes are jump cuts (D-220) | `test_dashboard_browser.py` (opt-in) |

## 5. Evidence States

Every displayed value carries one of four states. Collapsing them into a single
placeholder destroys the distinction Law 0 exists to preserve.

| State | Meaning | Rendering rule |
|---|---|---|
| `fresh` | current, sourced | full contrast |
| `delayed` | value exists, is old | de-emphasised, age shown |
| `disconnected` | source exists, nothing arriving | marked missing, not zero |
| `unavailable` | this device has no such source | omitted, or named as not present on this device |

These four are **per value**, not per transport. A WebSocket drop is a page-level
signal and must not reuse this vocabulary. The server judges the state and
exposes the threshold that produced it; the client displays the string and does
not recompute it (G4, D-72 S3/S4).

`delayed` is not `disconnected`, and neither is `unavailable`. Fleet must never
draw an unreachable robot as healthy: loss of contact is its own state.

The robot face translates this law in its own grammar rather than the four
rendering rules: the wake card expires (`hold_s`) and the face returns to the
intent display, so a stale value is erased, not aged (D-153 session 3, F-04).
A value with no source still never renders as a measurement — missing battery
draws `--`, never `0%` (Law 0).

**Known overlap with §8:** `unavailable` here and capability `not_provided` can
name the same fact ("this robot has no lidar"). They stay two tokens. A concept
view reads inventory; a value binding reads `evidence`. Do not merge the
renderers.

## 6. Colour Sets

| Set | Use | Constraint |
|---|---|---|
| categorical | series identity (route, alternative, goal, marker) | never used for status |
| status | threshold crossings only | never used for series, never decorative |
| neutral | everything else | default for all gauges below threshold |

Gauges read as margin: neutral until a threshold is crossed. A metric is not
assigned a colour because it is a different metric.

Map rasters are a shared contract **inside one pipeline**: the free and occupied
values `control/web/dashboard.html` draws must equal
`sensing/map_raster.py` (BGR in the PNG, RGB in the CSS tokens). This is
checked in `control` (`test_map_raster_color_contract.py`), not commented.

`core_api_web/web/map.js` is a different pipeline. It paints `/api/v1/map` in the
browser (four occupancy buckets, different thresholds) and is bound by the
colour-set law only. A `tokens.css` ↔ `dashboard.html` assertion has no legal
home under D-73: no harness module owns both packages. That limit is recorded
here, not treated as a pass.

## 7. Surface Grammars

Layout follows from the viewer's time budget and input device. This is where
surfaces are deliberately unlike each other.

| Surface | Time budget | Input | Grammar | Declared viewport (D-201) |
|---|---|---|---|---|
| Robot console | ~2 s, standing beside the robot | pointer and keyboard, possibly gloved | spatial | ≥ 1366×768 (stacks below 720 px width) |
| Device runtime | ~30 s, seated | pointer | procedural | scrolls by design |
| Fleet | ambient, while doing other work | keyboard-first | exception | 1920×1080 site PC |
| Robot face | ~0.5 s, walking past | none | intent | 320×240 LCD at ~1.5 m |
| Game host | one match, standing at the laptop | keyboard | focal | 1280×800 |

### 7.1 Console — spatial grammar

Fixed three-region split: sense, observe, act. No page scroll; position is
memory. The frame fits at the declared viewport: the act column neither scrolls
nor crushes — a control that silently collapses to nothing is worse than an
overflow (D-201). Editing a policy is procedure, not operation; it lives in the
inspect view. Capability panels occupy role slots and never reorder when a device is
added. When content exceeds the viewport, the sense region scrolls while observe
and act stay fixed.

### 7.2 Device runtime — procedural grammar

The only surface where scrolling is allowed, because scrolling is the procedure.
Order follows bring-up order: power, host OS, network, DDS domain, ROS graph,
release, commissioning. A stage that depends on an earlier stage is placed below
it, never beside it — a multi-column grid erases the causality. Step numbering
is legitimate here and only here, because the steps are a sequence.

### 7.3 Fleet — exception grammar

The default view contains only robots needing attention; healthy robots are
absent, not green. The full roster is an explicit action. Navigation is
keyboard-first: traverse exceptions, then enter one robot's console. The colour
budget is tightest here — one robot in twenty in trouble means one coloured row.
Danger is a fill: a critical tag is paper ink on a crit fill, never crit text
(D-202). The whole page fits the declared site-PC viewport — an ambient surface
does not ask to be scrolled; the roster list scrolls inside its own frame and
the map shrinks before the page grows (D-201).

Fleet failure must not present as robot failure (FLEET SRS §1.2). Unknown is
rendered as unknown.

### 7.4 Robot face — intent grammar

Legible at about 1.5 m within about 0.5 s, without reading text. It shows
intent, not state: the direction it is about to take, not a mode name. This is
the one surface where a second typeface is justified, chosen for small-size
low-resolution rendering. Danger is a fill here too: an alarm sentence
(E-STOP, FAILED) is paper ink on a crit fill, never crit text — the pixel
gates live with the renderer tests (D-202). The bystander's channel is shape,
colour and expiry, not words; row labels stay machine acronyms because the
values are server enums — translating one without the other mixes vocabularies
without helping the passer-by (D-221).

The PWR-003 wake card is the one state-bearing exception: on wake it shows a
state snapshot (battery margin, E-stop) for a fixed `hold_s`, then the face
returns to the intent display (D-153 session 3, F-04). Its evidence semantics
are §5's face paragraph — expiry, not ageing.

### 7.5 Game host — focal grammar

The match board has no thresholds, so it has no status colours to spend. Its
one warm accent is the ball — the focal object the match is about. Team
identity stays cool-tone, and loss/HOLD is named in text, never only in colour.
The halt row never leaves the viewport at the declared laptop size — the focal
object may shrink, the stop may not (D-201). This surface is off the shared tokens by design (D-101); this paragraph fixes
its colour law (codified D-153 session 11 from existing practice).

## 8. Capability Presentation

A capability supplies *what*. The surface owns *how*.

A capability contributes a data contract, a semantic role (sense, observe or
act) and a priority. It does not ship a renderer. `mobility.navigate` is a
half-screen map on the console, one row with an ETA on Fleet, an arrow on the
LCD, and a node-liveness line on the device runtime.

Presentation state has four values, and `blocked` must carry a reason:

| State | Meaning |
|---|---|
| `available` | usable |
| `constrained` | usable within stated limits |
| `blocked` | not usable now, with the reason named (safety policy, node down, model missing) |
| `not_provided` | not provided by this device — omitted, not greyed |

`not_provided` is the former `absent`. The rename avoids clashing with §5
`disconnected` (once called `absent`). A greyed button with no reason
contradicts the 501 the server already returns. Inventory omits
`not_provided` ids; it does not list them as disabled.

### 8.1 Two capability documents (D-68)

CAP-001 (`GET /api/v1/system/capabilities`) stays the feature-gate document and
its body does not change. Concept ids, dynamic `available`, `state`, and
`reason` live on inventory `descriptors[]` and `capability_ids`. A concept-level
view reads inventory; a feature gate reads CAP-001. These are not merged.

## 9. Composite Assets — target, not v1

Per D-71 and D-55, v1 is a single-device asset. The rules below apply when
composition is enabled, and are recorded now so the console does not have to be
rebuilt then.

1. **Slot is decided by role, not by device.** A manipulator's grip control
   lands in the act region beside the base's drive pad. Adding a device never
   reshuffles the layout.
2. **Safety does not compose.** Devices own their local safety (concept 09), but
   the surface has exactly one emergency stop, at asset level, in a fixed
   position. Per-device stop buttons are a hazard.
3. **Each device brings its own evidence.** Staleness is owned by the panel. One
   device going quiet dims only its own panels.
4. **Refusals name their author.** In a composite asset "it stopped" has several
   possible authors; the operator cannot choose a recovery without knowing which
   one refused.

## 10. Conformance

These are contract tests, in the style the repository already uses, not review
guidance:

- surface stylesheets contain no raw colour outside the token file
  (`src/core/web_common/test/test_ui_token_contracts.py`)
- a status colour never appears in a categorical position (same)
- client map raster values equal the server renderer's values
  (`src/runtime/control/test/test_map_raster_color_contract.py` — control
  pipeline only; see §6)
- a `blocked` capability without a reason fails
  (`src/runtime/core/test/test_capability_descriptors.py`)
- evidence state is present on every rendered telemetry binding
  (`src/runtime/core/test/test_dashboard.py`, `test_evidence.py`)
- a surface stylesheet declares no tokens of its own — no alias vocabulary
  beside the token file (`src/core/web_common/test/test_ui_token_contracts.py`, D-92)
- spacing comes from `--space-*` and type size from `--text-*` (same)
- the operate view does not scroll and the map keeps the observe region
  (`src/runtime/core/test/test_console_layout.py`)

D-73: a test that opened both `web_common/tokens.css` and
`control/web/dashboard.html` would have no owning module. Do not add one.

## 11. v1 Mapping

| Section | v1 meaning | ADR |
|---|---|---|
| §2 surfaces | operator console is CORE `/dashboard`; device runtime is the same page; control `web_node` is not that console | D-23, D-75, **D-77** |
| §3 laws | binding on shipped surfaces now | D-32 |
| §5 evidence | server-judged `fresh`/`delayed`/`disconnected`/`unavailable` on `StateSnapshot.evidence`; stale teleop blocked | D-23, **G4** (HOST slice; DEVICE HOLD) |
| §8 capability | CAP-001 gate live; inventory descriptors carry `state`+`reason`; `blocked` requires a reason | D-11, D-68 |
| §9 composite | not v1 | D-55, D-71 |
| §10 conformance | contract tests listed above; cross-package token assertion has no D-73 home | D-61, D-73 |
