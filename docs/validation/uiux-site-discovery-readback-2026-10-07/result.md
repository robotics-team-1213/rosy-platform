# Site discovery and UI candidate readback — 2026-10-07

**Assessment: FIELD discovery observed; current UI candidate remains HOLD.** Read-only Tailscale SSH to the existing site PC on 2026-10-07 at about 08:59 KST found:

- The user mDNS bridge timer active, with four recent journal entries reporting two services delivered.
- Two distinct robot `_rosy._tcp` instances, one `_rosy-fleet._tcp`, and one `_rosy-overhead._tcp` in host Avahi. The Fleet container's service UID 10001 resolved both advertised robot `.local` names (`2/2`). Discovery and resolution do not prove authenticated Fleet enrollment or UI display.
- Fleet, Vision, and proxy containers healthy, all tagged `e64815c5137e91aee261cee9569cd592e74afed0`. The local candidate was `0d9180c62`; Git reports 19 Fleet web paths changed between those commits. The running site UI therefore cannot verify the current candidate's layout or behavior.

Sanitized command output: `X:/DevTemp/projects/rosy-platform/2026-10-07--site-uiux-readback/summary.txt` (SHA-256 `7938aa7ba85c25d23793b432d6e1fdbc8450fa3fd677751c2cb2d76db4968649`). Commands used `avahi-browse -atp`, the bridge timer/journal, `docker ps`, and `getent hosts` as UID 10001 inside the Fleet container. No device settings, credentials, motion, E-Stop state, or deployment were changed.

D-153 G2/G3 for the current candidate still requires its declared states and widths on the intended devices, authenticated site UI readback, and the user's eight-item operator walkthrough. A walkthrough of this older site image can report usability findings but cannot accept the current candidate.
