# OMX opposing-arm stacking — measured execution entries

Latest actual CAD result: **nine-container 3×3×3 gapped packing PASS**, run
`2cdbdd56df3851aeb9ff2701e2014bdd` at commit `bb39f438a5e1df2ae23da08eb356e0627a1d5360`
(D-929: rows3.5mm apart, band2-5mm, envelope90×97×90mm). All nine released,
final measured gaps3.22-4.00mm, no unstable box, strict whole-stack stability
(speed from the pose change per0.1s step), SDKexit0, import, continuous native
video11674frames and owned shutdown/GPU release verified. One seed42 nominal
IK-reference condition only; offset/reverse, learned policy, hardware and field
acceptance are not covered.

Earlier actual CAD result: **three-bar, three-floor column PASS**, run
`8858bf075b975578aa490ae91bb32820` at
commit `4f63cd59923b14be4b98b9c0f01e4a2314358054`. This is the authorized3×1×3
fallback: one90×30×30mm long container per floor in90×30×90mm, arms0→1→0.
All three released floors, whole-stack stability, continuous native video and
owned shutdown/GPU release passed. Nine-container90×90×90mm packing remains
unaccepted. This is one seed42 IK-reference condition, not learned-policy,
hardware or generalization acceptance.

## Current extension: varied layers and continuous native video

The original accepted one-floor case below is preserved. New allowlisted
`omx-map-container-stack` uses the same workplate/conveyor/arms with seed,
layers(1/3) and case(nominal/offset/reverse). Three layers mean nine
90×30×30mm containers, three per layer, in a90×90×90mm target.
The current center-first proposal uses1→0→2 or reverse1→2→0, retaining actual below-row support and assigning
the nearest arm. Nominal infeed consumes XY±1mm/yaw±.01rad; offset/reverse
consume X±5mm/Y±8mm/yaw±.08rad. Tolerances and contact/stability gates remain.

Source `83756cf68e` adds a fixed actual800×600 camera at10fps, strict native
ReferenceTime receipts and physical ticks, bounded fresh-readback waiting,
full video decoding and registered byte hashes. The film includes preparation,
pickup, carry, release, retreat and settling; it is not a phase-PNG montage.
The code is an IK reference, not ACT/RL or hardware acceptance.

| Condition | Run | Current result |
| --- | --- | --- |
|1layer nominal42 | `e64626136b965d3296768110654bbf82` | SUCCEEDED; contacts/video/import/cleanup verified |
|3layers nominal42 v1 | `7f874ccafca7525ba1c7bed552e7ef13` | FAILED;5stable placements,6th descent contact |
|3layers nominal42 v2 | `599927a7261756ad9380b6369e386327` | FAILED;3stable placements,4th landing outside envelope |
|3layers nominal42 v3 | `4251d70fd2d359daba54ea348d9e1bfe` | FAILED;8stable placements,9th outside Y envelope |
|3layers nominal42 v4 | `0b47f13c80cf551a94894bb604aa6407` | FAILED;2stable placements,middle gap insufficient; opening blocked |
|3layers nominal42 v5 | `2a6c4f845b0e5b9384b2a84c5bff450d` | FAILED; center stable,second outer landing outside Y envelope |
|3layers nominal42 v6 | `0c2a8b3600b152dda466df208ab65a1e` | FAILED;6stable placements(two floors),seventh settling angular speed exceeded limit |
|New CAD1layer nominal42 v7 | `868ccb4935795d9a8b9c7c384e28c24a` | Registered UNKNOWN; first bar physical failure,0accepted; not accepted |
|New CAD1layer nominal42 v8 | `3c61b55f3ffd505baf2b650b748fc5fd` | FAILED before physics: invalid marker prim name; cleanup confirmed |
|New CAD1layer nominal42 v9 | `53dd0db4184b53fea9febd571b0f15de` | UNKNOWN; transfer planning budget failure before leveling; owned processes exited, GPU release unconfirmed |
|New CAD1layer nominal42 v10 | `bb4db64f1fc55bb78b67f3e0f5b5ab76` | SUCCEEDED;3/3 bars, physical leveling/regrasp, video/import/cleanup verified |
|New CAD3layers nominal42 v11 | `c89ae2f181a55710a4431510ecd2bf6c` | UNKNOWN;1accepted,second held footprint blocked before opening; not accepted |
|New CAD3layers nominal42 v12 | `b480884f0d2d50a990f872fb0ac5d3d6` | FAILED; experimental held-motion threshold timed out before first placement; cleanup confirmed |
|New CAD3layers nominal42 v13 | `5cd908e4b91a5e97bcf3ebaf1581e228` | FAILED during preparation; FileNotFoundError, no task report; cleanup confirmed |
|New CAD3layers nominal42 v14 | `dce2a538f0395a978170e30d1f5c42ae` | FAILED;1accepted,second footprint remained outside envelope after bounded wait; cleanup confirmed |
|New CAD3layers nominal42 v15 | `62ae29fa948c5bf3ad8b01a7b2ebfc93` | UNKNOWN;1accepted,parallel regrasp reduced tilt but center drift left insufficient outer width |
|New CAD3layers nominal42 v16 | `a970a0009e5254c9814efa5f96b3a2f2` | FAILED; fixed center bias worsened landing drift;1accepted,cleanup confirmed |
|New CAD3floor column42 v17 | `58f406305b1554a29a3f5ef17dfe1e01` | FAILED;three bars physically stacked,third stability window exceeded angular-speed limit; cleanup confirmed |
|New CAD3floor column42 v18 | `8858bf075b975578aa490ae91bb32820` | SUCCEEDED;3bars/3floors,strict whole-stack stability/video/import/cleanup verified |
|New CAD3layers nominal42 v19 | `2e8b9c3d894d578398f7358d8adb4f9c` | FAILED output_limit; five placed, sixth held when plan exchanges reached259files; cleanup confirmed |
|New CAD3layers nominal42 v20 | `42a8331fe2085ac6944c35b17d95519b` | FAILED;seven placed (two full floors+third center), eighth blocked by prefix angular speed.1004rad/s; video/import/cleanup verified |
|D-929 gap3layers nominal42 v21 | `812a28df320c58c1bad8abfcf96ea3c6` | UNKNOWN; eight placed, ninth held when the1590s SDK budget ended; no report; owned processes exited, GPU readiness false at the cleanup gate |
|D-929 gap3layers nominal42 v22 | `ce56c57aef58554497f73388367db7bf` | FAILED; all nine placed, gaps2.74-3.68mm; final window blocked by PhysX stale velocity of sleeping boxes; video/import/cleanup verified |
|D-929 gap3layers nominal42 v23 | `fa6f944c1efe5c7794f3400e448daa79` | FAILED; eight placed; prior-stack window before the ninth leveling release not reached in10s (outer row0 column sway); video/import/cleanup verified |
|D-929 gap3layers nominal42 v24 | `5ae3b5c5a5695b57a7c1c0c28d482a2e` | FAILED at setup; exact float readback of a32-bit USD threshold; cleanup confirmed |
|D-929 gap3layers nominal42 v25 | `b7b785fd308d56448f751290b75298ba` | FAILED; scene stabilization (prior off) moved the held box, first leveling release did not converge; reverted |
|D-929 gap3layers nominal42 v26 | `39bebc33ccb75f409ba2f5700dadc616` | UNKNOWN; settled-cargo sleep threshold0.0→5e-5 had no effect: same failure as v23 frame for frame; GPU occupied by other jobs at cleanup |
|D-929 gap3layers nominal42 v27 | `b326b5857ef955aca66141fa9ac78fab` | FAILED as v23, with per-box diagnosis: boxes3,4,6,7 reported.10-.18rad/s while moving ≤6um per0.1s |
|D-929 gap3layers nominal42 v28 | `a4e9f3f4ed6b50a2b84a04f82fae509d` | FAILED unsafe_output after six placements; transient entry gone afterwards; supervisor now logs it |
|D-929 gap3layers nominal42 v29 | `2cdbdd56df3851aeb9ff2701e2014bdd` | **SUCCEEDED**; nine placed, gaps3.22-4.00mm, video/import/cleanup verified |
|3layers offset43 | Not started | Not evaluated |
|3layers reverse44 | Not started | Not evaluated |

The v1 sixth bar tilted approximately1.45degrees during lowering and contacted
the previously placed upper-row neighbor with0.07046N. Bilateral finger contact
remained, but the unsupported-hold interlock correctly blocked opening.
V2 added a1mm descent margin away from that neighbor before final feedback
alignment at the measured lower-height footprint. It stopped earlier: the
fourth bar drifted in X during release/landing, ending at131.1315mm with
Xmax176.2312mm,0.2312mm beyond the allowed outer envelope. All three lower
bodies remained stable. Both failed runs had SDKexit0/import/video verification
and owned cleanup; neither establishes completed three-layer stacking.

V3 source `9ba09f38acb585a697b223f3b7c484498f50c7d4` retains the1mm approach
and reduces opening acceleration from0.1 to0.025rad/s² in the new container
fixture only. LegacyCUBE0.1,15mm height, effort caps and acceptance tolerances
remain unchanged. Opening diagnostics sample at20Hz to resolve the roughly55ms
freefall. Related motion/recording/legacy tests:51passed,0NEW. Earlier full
Isaac/transport/release/document checks:597passed,1skip,0NEW at7ddaf12cd7.
Registered large-artifact downloads now allow180seconds rather than50,
retaining byte/hash limits;43transport tests passed and the timed-out v2 movie
was recovered. Original partial snapshots remain identifiable as partial.

V3's ninth held center already reachedY31.3316mm before opening and settled
at31.5662mm: accumulated neighbor/held-width correction exhausted the original
envelope. Its4986-frame498.6s failed film remains preserved. V4 source
commit `cc55059b7d18d7a7b0bc6a87da77334a166022a4` changed to outer-first and measured
gap, preserving acceptance. Its first two commandsY±30.5mm settled at
−30.0198/+30.0891mm; the tilted held middle could not fit that measured gap.
The pre-opening interlock stopped it, with1419frames141.9s of native video.
V4 full remote Isaac/transport checks:524passed,1skip; SDKexit0/import/video
verification/owned cleanup confirmed for both failed physical runs.

V5 proposes center-first with independently computed outer targets, using
the actual settled center face and held projected width. A projected outer
footprint must fit the unchanged envelope before opening; neighbor and swept
jaw vertical clearance remains2mm. This removes cumulative three-row correction
and the enclosed middle insertion. Actual higher-release landing remains an
unverified experiment until independent complete nine-body runs pass.
Source `1327257095e462feb51dbbee790709134aa0a409` passed52 focused remote
container/recording/legacy-cube tests with0NEW and read-only implementation
review. This source includes measured-footprint readiness bounds; a40µm
tracking error must not admit an actual footprint outside the envelope.

V5's center remained stable atY−0.32246mm. The next outer bar released at
Y−30.5364mm/Z81.1723mm and settled atY−31.5788mm, withYmin−46.6367mm.
Its1118-frame111.8s failed movie is preserved. The full-circle swept-pad bound
alone required cargoZ60.98374mm, below the original62mm release target;
the new whole-body vertical separation instead forced81.173mm. Since measured
lateral separation already excludes body overlap, V6 proposes retaining swept
finger clearance while removing only that redundant body-height requirement.
The lower release is a controlled simulation hypothesis, not accepted behavior.
V6 source `d517d88d7d4d62de54c8496b8679080c355c55e0` passed full remote
Isaac/transport tests with0NEW and read-only implementation review before
starting its nominal physical trial.
It completed two floors, then stopped during seventh-bar settling: at tick45681
the top center's angular velocity magnitude exceeded0.1rad/s
([-0.111892,-0.010383,0.009105]rad/s), while the prior six remained stable.
The native3814-frame381.4s movie and full report are retained; SDKexit0,
video/import verification and owned cleanup were confirmed. No variation run
started. This is incomplete three-layer acceptance, despite seven placed bodies.

### Newly uploaded actual map source

The user then identified newer actual-map material:
[최종 맵 세팅 자료 (2026-10-28)](https://winna1492.atlassian.net/wiki/spaces/SP/pages/13205531),
v1, modified2026-10-29T10:57:09.401Z. Its original World STL(att12681256),
World STEP(att12583007), SolidWorks ZIP(att12550209) and DWG(att12550203)
were downloaded read-only. STEP explicitly defines millimetres; STL itself
has no unit declaration. Original STL sha256:
sha256 `dd91457a4a8d17d7fbb4fbfdb12dff9c2ae98e92e74760231c9ec08aa377f3cc`.
STEP sha256:
sha256 `c455f11ab450cfcb9633a58387b0c0ec56f56727d23b4736ba5853334708f891`.

This source is distinct from derived simulation record12615681 and older
photo/CAD source8683759. The STEP root contains three instances of the same
Follower assembly and no named Leader product. Two opposing candidate assembly
origins are330mm apart, whereas the current photo-derived simulation uses260mm.
Assembly origins are not surveyed motor axes. Plate/conveyor geometry and frame
alignment must be checked before claiming that this simulation reproduces the
new actual map. Existing trial results apply only to their recorded nominal
fixture. Raw team CAD is retained outside the source repository.

### CAD workcell implementation and preflight

Source `556cb7720ad180a66219e2809609a5982ef4a3d9` implements the selected
Stage1 opposing pair as a workcell proxy. CAD millimetres map to simulation metres
by X=(Zcad+355)/1000,Y=(Xcad−793)/1000,Z=(Ycad−19)/1000. The plate is
603×760×18mm, with opposed bases330mm apart at its72mm top above BASE.
The original source contains three Follower assemblies; Stage2's third arm is
outside this task. BASE and Stage2 context dimensions are recorded; old road
paint and an unverified upstream belt are not transplanted into the CAD workcell.
This is a selected workcell reconstruction, not an import of all CAD mechanics.

The source planar belt face slopes4.567degrees and is85mm wide. A4mm-thick
collision proxy places its top on that plane and uses native orientation
readback. The task stop before the plate, pickup and90mm stacking envelope
are explicit experiment settings, not labeled CAD hardware. CAD assembly origins
remain unregistered to surveyed motor axes.

The lower pickup is approximately52.2mm above BASE,20mm below the robot bases.
The default SIM workspace correctly refused it. A named offline SIM scene now
admits lower points only for the exact selected base/yaw pairs and a bounded
external belt corridor; every sampled trajectory point, including its FK start,
is checked. Default/native profiles and joint position/velocity/acceleration
limits are unchanged. The planned sequence lifts vertically before transferring
over the plate. This admission check does not establish continuous full-arm
collision clearance.

Remote preflight:637passed,1skip,0NEW, including Isaac/transport, release
boundaries, document placement and owner frame checks. Read-only implementation
review approved the source for a first SDK trial. New-map physical execution
initially did not start: four official admission retries refused it, and read-only
diagnostics showed GPU free memory15824MiB/no compute owners but an occupied
shared model-code work lease. No peer process or lease was altered. The controller
created no run UUID or acceptance receipt during that initial wait. A subsequent
bounded retry found the lease available and started the first-floor run
`868ccb4935795d9a8b9c7c384e28c24a` through the normal owner. That attempt ended
as described below; no new-CAD first-floor acceptance exists yet.

### Inclined-belt failure and physical leveling protocol

V7 carried the belt's approximately−4.63degree pitch to release. Its first bar
was centered atX80mm before opening and settled flat at82.0501mm, beyond the
unchanged1.5mm position and1mm envelope limits. The SDK report therefore records
physical failure. The supervisor separately persisted cleanup=UNCONFIRMED and
UNKNOWN at revision3; later observation replaced the error at revision4.
Which cleanup/GPU probe subcondition failed was not retained. Exit2 alone does
not identify that subcondition.

Bounded read-only recovery preserved13regular files with SHA checks outside the
registered snapshot namespace. Independent report, whole-MP4 decoding and
manifest verification succeeded withtask_success=false. The564-frame56.4s movie
is4,357,885bytes and is linked from Confluence as a failed physical attempt with
registered UNKNOWN, not an accepted run. The unit later hadMainPID0, an empty
cgroup and matching invocation identity. A fresh GPU-ready observation at
2026-10-29T15:53:49Z allowed release of only this client's resource reservation;
the stored run remained UNKNOWN. No peer process or lease was changed.

Source `6094a0f7f61fbf738a56cc0ec3c00096d2300086` adds actual tabletop
leveling and regrasp. A120×100mm visual region atX−40mm/Y0 on the existing
Stage1 table receives the tilted bar. No guide wall, attachment or extra support
collider is added. Acceptance requires only measured table support, flatness
within0.01rad, low velocity/angular velocity and an unassisted stable interval.
The same assigned arm regrips the measured settled pose and proves a second
bilateral free lift before the original pallet sequence. Initial lift, staging
release, second lift, pallet opening and settling are ordered in the evidence.
Final pallet tolerances and forces remain unchanged.

Arm-specific staging yaw±pi/2 avoids crossing the existing wrist limit; the
whole approach/release/retreat/regrasp/lift paths passed offline owner planning
for both arms without changing joint limits. Table contact is appended only in
this new fixture. The continuous movie includes all staging/regrasp actions;
its time and byte rate must be measured before extrapolating to nine bars.
The64MiB movie and1800s service limits remain.

Source609 passed669remote checks,1skip,0NEW and read-only review. Its first
SDK attempt3c61 failed during scene construction because a negative sign in a
marker name was invalid USD syntax. No physical leveling happened; exit1 and
owned cleanup were recorded. Source
commit `2fa51ef713dfa5cc02f8db3c1ba1c1a711cb0909` changes only marker identifiers,
preserves positions and adds a scene-construction regression through the actual
map builder. Its38focused remote checks passed with0NEW, and read-only review
approved retry. The next run53dd failed before leveling: a near-zero wrist
angle chose an equivalent endpoint whose path crossed the wrist limit and
exceeded the unchanged planning budget. The planner now tries the original
preferred path first, then equivalent half-turn endpoints only when it fails;
every candidate retains the original workspace, joint, motion and frame limits.
Captured native requests with positive/negative wrist noise reproduce this case.
Run53dd remains UNKNOWN: retained cleanup observations show owned processes
exited but GPU readiness was false. Later readiness only released this client's
reservation; it did not promote the historical result.

### Actual CAD one-floor acceptance

Source `ff4474dc63dd0bc469aafe92a39615077121341b` passed677 remote checks,
1skip,0NEW. Run `bb4db64f1fc55bb78b67f3e0f5b5ab76` completed all3 bars
on the actual-CAD fixture, including physical tabletop leveling, regrasp,
second free lift, final support and unchanged settling gates. Registered state
SUCCEEDED, SDKexit0, import/video verified and owned shutdown/GPU release
confirmed. This is one nominal IK-reference run, not a robustness, learning or
hardware claim. Three-layer and varied-infeed acceptance remain pending.

Snapshot `bb4db64f1fc55bb78b67f3e0f5b5ab76-128c7070db3342468bc75bee608879a7`
contains the native final frame and3807 continuous frames at10fps/380.6s.
MP4:31,108,854bytes, sha256
sha256 `976547460ff451a6c5123ef0984fac757e0b44b12d1dd1eaa57528001ba98b5e`.
Report:1,404,060bytes, sha256
sha256 `d00fff7844f0e48e3c357285298612a4cdc0267abdfa5ee81e4103ddc1520aac`.
The final native frame was visually inspected. A simple nine-bar extrapolation
is1141.8s and93,326,562bytes: time is below the existing1590s SDK budget,
but this encoder would exceed64MiB. Container-only bounded encoding must be
checked before starting the nine-bar campaign; caps and physics stay unchanged.

Encoder-only source `c133ae7f0cc8c383ee87bdb4d0dbd1877c648890` adds a
positive-integer optional maximum bitrate to the existing recorder; only the
container caller chooses320kb/s with a one-second VBV. Other callers retain
their previous defaults. Remote34passed/0skip/0NEW include real ffmpeg encoding,
full decoding, frame count and timestamps on120 changing800×600 frames.
Read-only review approved the change. This bounds bitrate, not total size for
arbitrary simulation duration; the unchanged64MiB artifact check remains final.
Native capped-footage quality and nine-bar acceptance are separate checks.

### Actual CAD three-floor first attempt

Run `c89ae2f181a55710a4431510ecd2bf6c` atc133 completed one placement,
then blocked the second before opening: its measured Y half-width increased
from15.089837mm during carry to15.530232mm after descent. Angular velocity
was[-.262677,-.725640,.324395]rad/s, approximately.8rad/s; the held footprint
could not fit the original envelope beside the settled center row. The film
contains2413frames/241.2s,9,684,827bytes, sha256
sha256 `0e35b4758ab334019cea9a6192b3c02bb4cc7b45b83c1a64d7953742ce5e2762`.
Three-floor success was not reached. The supervisor recordedUNKNOWN with
owned processes exited and GPU readiness false. Later exact unit/invocation,
MainPID0, empty cgroup and fresh GPU readiness released only the client hold;
the stored result remainsUNKNOWN. Thirteen source-bound files were preserved
read-only under `recovered-unknown-c89ae2f181a55710a4431510ecd2bf6c`,
without an official snapshot.json.

Rejected candidate commit `f18b37ebb01d97ad15232834320a3ffec07ee509` waited at most5s
before each packing correction and final opening for three consecutive quiet
held-body observations spaced12control ticks apart. It immediately rejects
loss of bilateral unsupported hold or prior-stack stability; persistent tilt
still fails the original geometry gate. All five windows are recorded and
recomputed by the verifier and judge, with motion/contact/prefix and chronology
checks bound to corrections and the final release. RED7motion failures and
9provenance failures preceded implementation; final remote Isaac/transport
suite:604passed,1skip,0NEW, read-only reviewAPPROVE. Native runb480 then
timed out before its first placement: held angular speed.47197rad/s never met
the added quiet-window requirement. The earlier accepted one-floor release
also had approximately.428rad/s of held motion. Applying the released-body
threshold to this supported grip was unjustified. The four experimental
commits were reverted inea47449808; their tests and observations remain in
history. This experiment did not solve the problem.

Current source `53ac7274dac653a5b8e333763798d8894e448b69` instead retries only
the original typed footprint-unavailable error for at most600control ticks/5s,
using each new measured orientation. Contact loss propagates immediately;
prior-stack instability also aborts immediately. There are no new held-motion
thresholds or quiet-window claims. Original packing geometry, measured final
readiness and released-body stability remain unchanged. Four RED cases cover
transient/persistent geometry and immediate contact/prefix rejection; final
remote Isaac/transport suite592passed,1skip,0NEW and read-only code review
approved the change. Failed trials now retain their final diagnostic sample.

Run5cd at this source failed during preparation withFileNotFoundError and no
task report; SDK log existed, and owned cleanup/GPU release were confirmed.
The error's exact origin was not retained. A supervisor scan race was reproduced
on CPU and fixed inb5b2b2ef4852c51c054030c1360cfc7647132ef8: only an
enumerated entry disappearing beforelstat is skipped; other errors and all
limits remain. Two RED disappearance cases preceded53worker/control passes
with0NEW. This does not establish the historical cause of5cd.

Same-source retrydce passed import but still failed the second footprint after
the5s wait. Its final held orientation and half-width15.530192mm remained
almost unchanged. It endedFAILED withSDKexit0/import/video/owned cleanup
confirmed,2463frames/246.2s. Waiting did not resolve this persistent tilt.

Sourcea8b2bb506da0a66833bb372357036a2c670a97a6 changed the Table staging
yaws from±pi/2 to[pi,pi], keeping the long axis parallel to the pallet after
regrasp and avoiding the90degree in-air turn. Both arms' complete offline
paths and597remote tests passed,1skip,0NEW; read-only review approved.
Run62ae then completed one placement but still blocked the second: its held
half-width improved to15.243781mm, while the first center settledY−.390555mm.
The center negative face−15.419692mm plus held width and clearance required
an outer edge−46.007254mm, outside the original−46mm bound. RegisteredUNKNOWN
and physical failure were preserved separately from later ownership/GPU
reconciliation. Sixteen bounded files were copied read-only with SHA verification;
no official accepted snapshot was created.

Rejected experiment commit d056db1f20ce9dc758084699f6a457cfeb22cfba added a+.3mm
center release-command offset against that observed negative drift. Plan targets,
1.5mm final position and1mm envelope tolerances, support, contact and stability
gates remain unchanged. Three RED bias cases preceded598remote passes,1skip,
0NEW and read-only review. Native runa970 endedFAILED: first pre-openY+.3004mm
landedY−1.0735mm, worsening center drift and blocking the second bar before
descent. SDKexit0/import/video/owned cleanup were confirmed;2333frames/233.2s
were preserved. The bias and its tests were reverted in5742fc3283, with history
retained. Fixed release bias did not solve the packed-grid problem.

### Authorized three-bar, three-floor fallback

The user explicitly allowed a3×1×3 long-container fallback if the full3×3×3
packing was difficult. New explicitcase `column`,layers3 uses three90×30×30mm
bars, one per floor, in90×30×90mm, with alternating arms0→1→0. This is not
nine-bar90×90×90mm acceptance. Existing nominal/offset/reverse grids stay
unchanged and unaccepted. The same actual CAD map, inclined infeed, tabletop
leveling, physical regrasp, original tolerances and video/cleanup gates apply.
Plan width and lower-bar support derive from the actual row count; immutable
inputs distinguish the new fixture. The final artifact gate also derives the
actual plan count: column requiresmapped-layer-3, nominal still requires9.
Five RED grid/reach cases and two RED artifact-gate cases preceded full remote
sourcec619e51353f6c38dc296fdd666afae6f141c1c90:606passed,1skip,0NEW,
with read-only reviewAPPROVE. Native run58f physically stacked all three bars,
but failed its final stability window. The third bar had nine valid observations,
then angular-speed spikes.129418/.122736/.111231rad/s above the unchanged.1
limit; the next observation four ticks later was.009664rad/s. Position and
support remained valid, as did the lower two bars. This is a failed run, not
three-floor acceptance. Official snapshot
`58f406305b1554a29a3f5ef17dfe1e01-e8c37d3c23ea41d0bb3690ee943f2d35`
recordsFAILED/SDKexit0/import/video/owned cleanup. The3855frame/385.4s film
is15,456,885bytes, sha256
sha256 `b5bbebee312bdc2c8f629844e0affdb78be920178c1ef079ce2260442f5609bd`.

Source `4f63cd59923b14be4b98b9c0f01e4a2314358054` changes only column
settling observation: wait at most10s for12consecutive observations, spaced12
control ticks apart, satisfying the original stable_box and TCP-retreat checks
for every placed body. Any sampled violation resets the window. The same
1.1s uninterrupted window, thresholds, physics and final judge remain; legacy
grid cases retain their previous timing. Three RED cases cover transient motion,
lower-body reset and persistent-motion timeout. Full remote609passed,1skip,
0NEW and read-only reviewAPPROVE. Native retry885 completed all three floors
and was registeredSUCCEEDED. SDK6.2.0.0 exited0; import/video verification and
owned process exit/GPU return were confirmed. The final observed windows have
12/12/13 samples spanning1.1/1.1/1.1333s, with maximum angular speeds across
all placed bodies.001018/.028356/.089140rad/s, below.1. Final center heights
are88.99999/119.00000/148.99968mm. Actual support, position, footprint and
TCP-retreat checks passed throughout each final window, including the final
cadence-padding observation. The original V17 failure remains preserved.

Official complete snapshot:
`8858bf075b975578aa490ae91bb32820-4c6fd13177a746cc9f4ec34201a99a8c`.
All15 registered file sizes and hashes were checked locally. The final native
frame was visually inspected. The full H.264 film has3880frames/10fps,
388.0s playback, ending at387.9s physics time; full decoding and frame receipts
passed the registered verifier.

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| mapped-video.mp4 |15553280|`1c12473d45316561b1b32c9a04f4a160ef8f78d3bc9a7e3ed3b939807c4264a8`|
| mapped-stack-report.json |1474793|`bde6a84f7311a77a4a486b13a4dfe99f8c37b0104aaa5b142d28fa85ce4e7642`|
| mapped-trial-1.png |269642|`6aace54edb96298fa4e81d6249e3e711d57778d35da514b344969435cdf246f4`|
| mapped-video.frames.jsonl |1081429|`a75f9efd3b8a73595e4851763a1d5226bb6666832bcdfe553bddeba43c9e1006`|

Published record: [Confluence map v24](https://winna1492.atlassian.net/wiki/spaces/SP/pages/12615681),
[plan v16](https://winna1492.atlassian.net/wiki/spaces/SP/pages/13336578),
[6m28s native column film](https://winna1492.atlassian.net/wiki/rest/api/content/12615681/child/attachment/att13894036/download).
Uploaded film, final PNG and report were downloaded again and their hashes
matched the registered originals. Original CAD page13205531v1 was preserved.

### Nine-container packing past the outer-row block

Source `70762be0250b983628ec495a6abd91a2e36dd15b` allows.5mm transient tilt
overhang only while the held footprint is checked; the final envelope and
released-body gates are unchanged. Remote Isaac suite570passed,2skip.
Run2e8b passed the earlier second-footprint block and placed five
containers, then the supervisor stopped the SDK at259output files: every
planned motion left a request and frame JSON. The256-file bound was kept.
commit `c8fbb61dc7654799806661064b29281b1b107ddb` deletes only accepted plan
exchanges and keeps refused ones; one RED preceded571passed,1skip.

Run42a8 at that source placed seven containers: both lower floors full and
the third-floor center. Every placed box remained within.82mm of its target.
Before the eighth container's leveling release, the third-floor center box
(item6) measured angular speed.1004rad/s against the original.1 limit,
position error.09mm, finger forces zero. Its post-release window peaked at
.0998, and it reached.1198 while the next container lifted: the top of the
three-high center column keeps a small contact sway. SDKexit0,
import/video verified,9356frames, owned cleanup/GPU release confirmed. MP4
sha256 `370ad1096ee4d42875de8d1e47d64e74541a833e98d3a218ee313fc19f95b060`.
The single-sample prefix check before leveling and packing is not changed;
whether a speed-only prefix excursion may wait for the existing1.1s stable
window remains an open decision. Nine-container acceptance is not reached.

### D-929 gapped packing: nine placed, final stability not accepted

D-929 packs rows3.5mm apart (band2-5mm, envelope90×97mm) and waits for the
original1.1s window when a placed box exceeds only the speed limits.

- Run812a at `01efc3c153` placed eight in1,606s; the1590s SDK budget ended
  with the ninth held. No report; owned processes exited, GPU readiness false at
  the cleanup gate (UNKNOWN). `6cb76e6059` raised the container budget to
  2310s SDK/2520s service and lowered its film cap to220kb/s, keeping the
  64MiB MP4 bound.
- Run ce56 at `6cb76e6059` placed all nine. Final measured gaps were
  2.74-3.68mm, every box within.67mm of target. The final window failed:
  outer-column boxes5 and8 reported.014 and.021m/s for26s while their poses
  stayed fixed to1um. The reported velocity was not motion; its cause is
  unverified (cargo sleep threshold reads0.0, so it is not PhysX sleep).
  11856frames, MP4 sha256
  sha256 `518741d14bdcffc5e109b265070f1233b70a65e6dcfab9ab333a755b1b2790c4`.
- `684618d077` judges a box whose pose is unchanged since the previous sample
  as at rest; each window keeps that reference sample and the verifier recomputes
  it. Limits are unchanged. Remote Isaac suite629passed,1skip.
- Run fa6f at that source placed eight; before the ninth leveling release the
  prior stack never held twelve consecutive stable samples in10s. At the
  failure sample all eight were stable; the outer row0 column (boxes4,7) had
  moved18um since the last window with.06-.07rad/s. 10898frames, MP4 sha256
  sha256 `4589dbeb7e6466a3ab9102638c6b20759e4b375f5cd33c5749e59eacd444c2d1`.

Gapped outer rows stand as30mm-wide,90mm-high free columns, and PhysX keeps
them in small contact sway. Two cargo-only physics attempts did not help:
scene stabilization (`062ab8ec76`, prior flag off) moved the held box in the
fingers so the first leveling release never converged (run b7b7), and raising
settled cargo's sleep threshold from0.0 to5e-5 (`a6733a6076`) reproduced run
fa6f frame for frame (run39be,10898frames, MP4 sha256
sha256 `d822bcc731ef22b8e97e3e6fb7f88dbabab9bfe94e3b901a3e76290ae79c1ab2`). Both were
removed; the gapped fixture is back to `gap-v1` physics.

Run b326 (`28d32c8615`, refusal now lists per-box failures) showed the boxes
blocking the ninth window reported.10-.18rad/s while their poses moved at
most6um per0.1s step: Isaac's instantaneous cargo velocity is solver chatter.
`67c54a1913` judges speed as the pose change over each sample step, limits
unchanged, verifier recomputing it. Run a4e9 at that source was stopped after six
placements by a transient unsafe output entry; `bb39f438a5` makes the supervisor
log such an entry (rule unchanged). Run2cdb at `bb39f438a5` SUCCEEDED: nine
placed, final gaps3.22-4.00mm, no unstable box, 11674frames, MP4 32,166,823
bytes sha256 `f13396435622de0a68d7b8375c4cf6ad42fbf553d1e4fb32b9eec5929d6f4e2e`,
report sha256 `f8182360cdea01d6abc54ea4c7f7cc11c63c63b891f177daab2d3d8da800cb3f`.
The final frame shows the full gapped cube. ce56 and
fa6f ended SDKexit0 with import, video and owned cleanup/GPU release verified.
Nine-container acceptance is not reached.

### Historical nominal-map film

The recorded one-floor run produced1595frames,159.5seconds,15,815,824bytes.
Video sha256: `306900c65cfedd15a2d782860e1d08773d827c45dcd2f2c080c2df065dc16dde`.
Report457,592bytes.
Report sha256: `cb4b32d07e1541810c73caa7ca12075980ff3fffd9e441f9c2007c72433f9140`.
Frame receipts440,881bytes.
Receipts sha256: `b66f11521b62364054a6319a9a7b720a65eea26873e84a575c4e4bd24549a861`.
SDKexit0/import/video_verified and owned process/GPU release confirmed. Actual
frames decoded from the downloaded movie at3,80and158seconds were inspected.
Workspace snapshot:
`Rosy/artifacts/isaac/omx-container-stack-20261029/e64626136b965d3296768110654bbf82-c203886225894dd79d11a41b349f6c4e/`.
Confluence attachment13598721 on map12615681 was downloaded and hash-verified.
Initial recorder failures remain preserved; see the
[native-camera readiness lesson](../../solutions/runtime-errors/isaac62-native-recording-stale-reference-time-2026-10-29.md).

## Original accepted scope: Rosy Cam correction, one layer

The user rejected the earlier layout. Current `omx-map-cube-stack` uses fixture
`rosycam-edge-container-first-layer-v4`: one common yellow workplate, both arm bases
on that plate facing each other, a lower conveyor over the gray map, and an
internal 90×90×30 mm target for three 90×30×30 mm bars. It stops at one layer.
The retained scenario identifier does not imply a completed 90 mm cube.

Topology follows the user's correction and the actual ceiling/close camera
stills captured on 2026-10-29. Dimensions remain nominal: 400×420 mm plate,
30 mm plate top, 25 mm conveyor top, arm spacing 260 mm. The target rectangle
is provisionally inside the plate; its exact photo registration is unmeasured.
The conveyor terminal now approaches the plate edge along -X, ending at x=.201
(1 mm nominal gap). Its stop is at x=.203 and cargo pickup at x=.250, 20 mm
closer than the former parallel-belt arrangement. The upstream -Y segment is
layout-only; cargo turn transfer is unverified. Rows use arms A/B/B. Release
height is 15 mm and planned row clearance 0.1 mm; acceptance tolerances remain
1.5 mm in position and 1 mm on the outer envelope. Exact registration and
learned-policy acceptance remain unverified.

Green/orange/green cargo now has visual corrugation and end-door details;
the90×30×30mm cuboid collider and60g mass remain unchanged. The actual renders
were inspected. The50k/100k ACT models in Confluence10911748 belong to a
different original single-arm task. This scenario is an IK reference and
does not establish those models' real-arm evaluation.

The reviewed hardware-inclusive improvement plan is published at
https://winna1492.atlassian.net/wiki/spaces/SP/pages/13336578 and locally at
`Rosy/docs/superpowers/plans/2026-10-29-omx-act-palletizing-improvement.md`.
Hardware comparison and two-arm acceptance are required final outcomes,
with explicit native admission, model-lineage, metrology and human-ready gates.

### Current-map first-floor reference accepted: seeds42/43/44

The frozen source below passed all three declared independent seeds. G1 is
accepted for infeed XY jitter±1mm and yaw±0.01rad only. All three registered
reports have task_success=true, no failures, SDKexit0, verified import and
OWNED_PROCESSES_EXITED_GPU_RELEASED. This does not change the separate
ROS-SIM, ACT, RL, hardware or field gates.

Source `d7ffc7d77d87808df30e645824a77c1cc13ee96c`, run
`a6d51484942553919af9f9119b080747`, SDK6.2.0.0. Lowering only release
gripper acceleration from0.4 to0.1rad/s² produced a complete successful floor.
The velocity bound0.4rad/s, 15mm release height, leader/follower0.2/2Nm,
retention, tracking and acceptance gates were preserved. Diagnostic sampling
does not select the motion profile. Remote RED showed the missing timing helper;
focused GREEN36tests and full Isaac/transport467passed1skip/0NEW followed.

The registered report has task_success=true, no failures, SDKexit0, verified
import and OWNED_PROCESSES_EXITED_GPU_RELEASED. Actual final image
`mapped-trial-1.png` was inspected; `mapped-top.png` shows the initial empty cell.
Final container centers in mm were (129.720,-30.604,47.000),
(130.591,-0.129,47.000), (130.246,30.645,47.000), measured at the same final
settling tick. The report retains all
lift/contact/settling samples; the existing oriented-envelope tolerance is1mm.
Report sha256: `0276565f5a04fe12e4867656e57199d4e29c9636c77fb5edca24ed4be4c5f919`.
Report size1,191,889bytes. Workspace snapshot:
`Rosy/artifacts/isaac/omx-green-container-20261029/a6d51484942553919af9f9119b080747-f8f95ade14284433b9215c3c00008c81/`.

Seed43 also passed with the identical frozen source/configuration apart from
the seed. Run `4a717f4ed20957e3a84e622650e4b787` has no physical failures,
SDKexit0, verified import and owned cleanup. Report1,190,735bytes.
Report sha256: `52308c3168342671ca628e44f3052b78a722bd8264363627b2fb5e42a2112d69`.
Snapshot suffix `4a717f4ed20957e3a84e622650e4b787-96bf36227bef46b0bfdcc52d590f6eff`
is in the same workspace artifact directory.

Seed44 run `99bc2112cf2451d6b1c4ae820b36dc50` passed the same criteria.
Report1,196,697bytes.
Report sha256: `1bf5e95420f8fde33ab9bbe48e58d5a4007a6aaae2450a33cfa04ca7a8e4ffd3`.
Snapshot suffix `99bc2112cf2451d6b1c4ae820b36dc50-9b5febfb82f7459d94ff12603f4adeed`
is in the same workspace artifact directory. Its actual final image was inspected.
No learned policy, ACT50k/100k comparison, three-layer or hardware acceptance
is established by these IK reference trials.
The original0fc776e21a failure moved bar3 from Y30.482mm before opening to
31.295mm after opening with yaw-0.256degrees and Ymax46.496mm. That measurement
motivated the controlled slower-opening trial; it does not establish universal
robustness or measured real-cell geometry.

For seed42 the third bar's measured opening displacement fell from+0.813mm
in the earlier trial to+0.041mm, with opening-end Ymax45.646mm. Independent
read-only implementation review approved the change and verified the source,
fixture provenance, phase guards and actual report/image; it did not rerun tests
or extend the evidence to other seeds, learned policies or hardware.

### Initial G1 execution under the improvement plan

- Source0fc776e21a /02dce02eaefa526cb2ed5b33a47aefa5 rendered the colored
  containers with15mm release and-.6mm first-row bias. First2placements passed,
  third envelope failed. SDKexit0/import and owned cleanup were confirmed.
  Report sha256: `269aa3c768cfc4a3483ec34c8b81260afa036ffe69c0e06d530c244708db96e8`.
- Source7475c13614 /cf18003b080a5faea53dc7e74d3d1113 tested8mm release.
  B finger link7 contacted the previously placed Cargo0 with about6.45N
  vertical force; joint lag≈.046rad stopped further correction before the
  second opening. This explains why lowering below the safe gap is rejected.
  SDKexit0/import/cleanup confirmed, physicalFAILED.
  Report sha256: `e4c79ac874d05f884fc01c8a0b28fd04dcee488be309c7c8af89a679f55728d7`.
- Source23dd5d14ef /604342a0af85564c84d2e4c3039ca088 restored the known15mm
  release height and tested leader effort.2→.08Nm as one grasp-preload
  hypothesis. Actual effort readback was checked. The first placement passed;
  the second release correction did not converge, so opening was blocked.
  SDKexit0/import/cleanup confirmed, physicalFAILED. The lower effort is not
  adopted; default.2Nm is restored. No acceptance tolerance was widened.
  Report sha256: `a0299902f0e98d0b11449e7329a64dbcbae2ee2410c366fc90d73d75619dfba2`.

Remote23dd regression463passed1skip0NEW; focused32passed0NEW. The remaining
G1 work is safe placement/retreat geometry and packing validation, while
model artifact recovery and real-hardware admission investigation proceed
independently. No hardware motion or50k/100k comparison has been performed.

Each entry below retains its own geometry, source and outcome. Superseded-map
results cannot establish success for the current arrangement.

### Terminal correction and lower release: bounded observations

- Source `534c98c0a4`, run `9ccf9d73839550d78980a28a10c05093`: terminal
  transported cargo from x≈.295 to .250 and stopped it at the plate edge.
  First placement passed; second ended at y=1.846 mm and failed. Opening
  snapshots located loss of finger contact around .583 s and first landing
  around .658 s, with approximately 7.93 N vertical contact force. This run
  had SDK exit0, verified import and confirmed owned cleanup.
  Report sha256: `66546cd390b9c440659fb70700058ac90ee2bceaa0c309f1b55112879e9c5c3c`.
- Source `81bae67682`, run `f0de57a9651455ebb5d828bc17a06d5b`: reducing
  release clearance35→15 mm retained the initial observed30 mm lift proof.
  Two placements logged passes, then an arm-A correction for the far row
  requested a point below the base and the owner planner refused it. SDK
  exit1, no final physical report. Owned cleanup was confirmed. These partial
  observations are not a completed layer or verified import result.
- Source `edbf49d6e0`, run `db17b3d401c45e13ac3f032371a8d3b5`: assigned
  the far row to the nearer arm B, blocked further correction after >.03 rad
  joint tracking error, and preserved bounded planner-refusal diagnostics.
  The raw report and artifact manifest passed independent read-only checks.
  All three bars settled, but the third center y=.031017 m plus its oriented
  extent exceeded the envelope tolerance by about21 µm. Physical task FAILED.
  Worker state remains UNKNOWN because its final cleanup check was not
  confirmed; no accepted final manifest was published. Later independent
  checks found MainPID0, no owned cgroup and GPU ready. The UNKNOWN record was
  retained and only its owned stale resource reservation was released.
- Source `c1786ef9d6`, run `254a87c630f8581dbdc53a5218438a36`: row
  clearance .2→.1 mm, with unchanged pose/contact/envelope criteria. Approved
  seed42 retry links the previous run as parent. SDKexit0, import verified,
  owned cleanup confirmed, physicalFAILED. All3bars settled, but the third
  center y=.031203907 plus oriented half width reached maxY=.046420896,
  exceeding the permitted .046 by .420896 mm. A rendered three-bar layer is
  not acceptance. Registered report786395 bytes.
  Report sha256: `3b8228db09636b50ae3e056ff85b5e691a03e0a2492431723c7734a7397bdcc4`.
- Source `5c89f3d1f3`: compensates the repeatedly observed positive first-row
  opening drift with a -.6 mm first-row release bias. The nominal acceptance
  targets and all position/contact/envelope tolerances stay unchanged. Focused
 32tests passed0NEW. Physical retry was refused by GPU admission while another
  compute process held194MiB; its result remains unverified. No unrelated
  process was stopped and no admission check was bypassed.

Validation: terminal focused27passes; lower-release focused29passes; nearer-arm
and final clearance focused31passes, each successful invocation0NEW. Source
`edbf49d6e0` broad regression807passed1skip plus one failure: an existing
report checksum was on a separate unlabeled line and triggered the entropy
guard. Metadata-only `972f2ae2d1` put its integrity label on the same line;
all80 release-boundary checks then passed0NEW. The scanner was not relaxed.

### Corrected layout, seed 42: scene rendered; first layer FAILED

Source `76587c5124a18760c8ef04ac2d5e9533e8af7d6e`, run
`3c2016972fc05704a1e30382efb37133`, Isaac Sim 6.2.0.0. The SDK completed
with exit 0, verified import and `OWNED_PROCESSES_EXITED_GPU_RELEASED` cleanup.
This is a failed physical task, not a completed layer or a trained policy.

Actual `mapped-top.png`, `mapped-initial.png` and `mapped-side.png` show the
common yellow plate, opposing bases, lower external belt and internal square.
The first bar passed lift, release and settling. After the second release,
the first and second bar centers settled at y=-32.624 mm and -2.624 mm,
respectively, outside the ±1.5 mm target tolerance. The next infeed was blocked.
The release sample was near the commanded pose; displacement appeared after
opening. The release/contact mechanism needs further diagnosis; no cause is
asserted from this observation alone.

Registered snapshot: `Rosy/artifacts/isaac/omx-opposed-floor-20261029/`
`3c2016972fc05704a1e30382efb37133-780cd59e10cf449db3609358875dedc5/`.
Report sha256: `119cab4bc340c10f70537b3790a71e4594ca827d8788a52170ca5809eb97f723`.

Remote validation for that source: 13 focused planning/acceptance tests passed;
broader Isaac/remote/OMX-owner/document regression: 514 passed and one ROS
xacro-overlay skip; affected guards: 336 passed. Each successful invocation
was compared with `test/known_failures.py`: zero new failures. Harness lint:
zero errors, 39 pre-existing status warnings after updating verification records. Exact camera registration, real
dimensions, first-layer physical success and learning success remain unverified.

CE: 미해결 — corrected scene is observed, but metric registration and the
post-release displacement remain unresolved. No solved lesson is claimed.

Each dated entry binds its own source, run and outcome. The earlier three-bar
fallback success is recorded separately in
[the mapped stacking record](../omx-map-stacking-2026-10-29/result.md).
It does not establish nine-bar cube success.

The target uses nine 90×30×30 mm, 60 g bars in three rows and three layers,
inside a nominal 90×90×90 mm envelope. The Confluence page 8683759 plywood CAD
and field photo remain the map source; workbench registration is nominal and
photo-derived, without hardware calibration. Near rows use arm A, far rows arm B,
and the middle row alternates by layer, within the nominal SIM planning profile.

The fixed `omx-map-cube-stack` scenario runs one seed within the existing 900 s
service / 870 s SDK budget. Three independent seeded passes are the intended
repeatability check. Cargo enters only at external infeed; subsequent transport
uses physical contact. Original lift, expected support, release, retreat, speed,
position and envelope tolerances are retained. Reference and learned-policy
success remain separate; camera and hardware acceptance are unverified.

## 2026-10-29 — initial seed-42 cube attempt: FAILED

Source `5ea2fc7e5d3b87569ef5f2e1919a3389020c0d0e`, run
`eeb0dc35dfe158c9a42c1ac4001118b3`, Isaac Sim 6.2.0.0.
The first bar passed. After the second release, cargo centre y was approximately
0.055053 m instead of 0.045 m and rotation was about 90° around its long axis.
The bar had low final velocity, pallet support and no finger contact, but missed
the position criterion. The interlock blocked further infeed. Two of nine bars
were attempted; raw judgement was `nine_bars_not_completed`.

SDK exit 0, verified report, terminal FAILED and
`OWNED_PROCESSES_EXITED_GPU_RELEASED` were confirmed. Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/eeb0dc35dfe158c9a42c1ac4001118b3-a0679db0bc024c5c8d5bfee29804e214/`.
Report: 248,768 bytes,
`sha256=d06c0c4f10b10cadc32b07d40a3171fff530624c9dbc411effb807f633540799`.
The actual final PNG was inspected. Intermediate carry/release observations were
absent, so this run alone does not identify the collision mechanism.

## 2026-10-29 — phase-observed seed-42 rerun: FAILED

Source `0b4f56d8b870a872a2d80516ac9be58ec04e23f0`, run
`9b7ff4d4133354bdb9e6d66e538520fe`. The physical commands and acceptance were
unchanged; carry, pre-release and post-opening snapshots were added.

The second bar remained nearly upright before opening. Its pre-release centre
y=0.04452506 m and measured y half-extent=0.01510753 m. The first bar's centre
y=0.01473950 m and half-extent=0.01513232 m. Thus their horizontal footprints
overlapped by approximately 0.455 mm while the second bar was held above the
first. After opening, the second bar rolled approximately 90° and moved to
y≈0.055053 m. This supports correcting the observed placement overlap before
the gravity release. It is not a general simulator-defect finding.

Both expected finger contacts were measured before opening; final pallet support
and finger release were observed. The same position failure blocked progress.
SDK exit 0, verified report, terminal FAILED and owned process/GPU cleanup were
confirmed. Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/9b7ff4d4133354bdb9e6d66e538520fe-35b06ac6b63844bea02bb7b35919c014/`.
Report: 290,019 bytes,
`sha256=3f528a04abfa459b90a37e2669000317cef7ef88d078c879065316a8b0d16ed9`.

## Source verification at the measured-release stage

Source `4b88808273` passed 428 remote Isaac tests with one ROS xacro-overlay skip,
exit 0 / 0 NEW. This includes nine assigned-arm reach cases, expected-row support,
earlier-bar disturbance rejection, strict speed, report bounds and worker outcome
contracts. Source `5ea2fc7e5d` separately passed 20 remote transport tests.

The measured-release implementation computes the TCP correction from observed
cargo centre and oriented neighboring footprint, with a 0.2 mm clearance and a
bounded number of iterations. The independent reviewer identified the need for
a final retention/clearance check after the last correction and before opening.
This source verification is not a passing physical cube run.

CE: 미해결 — the full cube release mechanism is under correction. The earlier
fixed-root lesson remains verified for the fallback; no new solved lesson or
full-cube success is claimed by these diagnostic entries.

## 2026-10-29 — final release gate stopped seed 42: FAILED

Source `2689a0c35a994e59bd7386705dd415d79f9d1d25`, run
`4fecd020591e5bfc9a8872f52de14fc5`. The final gate prevented opening on the first
bar after four measured-correction moves. Bilateral retention was present, but
position correction remained approximately 0.868, 0.866, 0.866 and 0.865 mm.
Thus this was a retained-cargo convergence failure, not a completed placement.

The repeated calculation anchored the next target at measured TCP position.
Because the held cargo and measured TCP shared the loaded-arm tracking offset,
that expression repeatedly produced almost the same absolute IK target. The
observed constant error was not integrated into the next command. A regression
now models constant loaded-arm tracking bias; the next experiment accumulates
measured cargo error from the previous commanded TCP target. Final retention,
50 µm convergence and 1 µm neighbor-clearance-deficit gates remain unchanged.

SDK exit 0, verified report, terminal FAILED and owned cleanup were confirmed.
Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/4fecd020591e5bfc9a8872f52de14fc5-03e2e1845cf8453e82fc39f0b65a32e0/`.
Report: 85,388 bytes,
`sha256=b840fc676499a68799272c723d89340191d173d271245589fe37ea495dcd81b1`.
No later seed was started by the failed-run orchestration.
