# Site UI image and mDNS recheck — FIELD discovery, UI acceptance HOLD

Read-only check on 2026-10-07 around 22:30 KST. The existing site PC was reachable through its configured Tailscale SSH alias. This repeats the earlier [site G3 readiness check](../uiux-site-g3-readiness-2026-10-07/result.md) after the installed image changed. No settings, credentials, robot commands, or deployments were changed.

| Check | Observed |
|---|---|
| Fleet, Vision, proxy | All running and Docker health `healthy`; all image tags commit `ed006ce92cc4832619dc96d4d0e00f779b439ec9`. |
| Site discovery | Avahi active; two IPv4 `_rosy._tcp` robot services observed. Both advertised `.local` names resolved inside the Fleet container as service UID 10001. |
| UI image ownership | Fleet UI code is copied into the image by `deploy/site/Dockerfile.fleet`; `docker inspect` showed no bind mount over `/opt/rosy/src/site/fleet` or `/opt/rosy/web-common`. |
| Current candidate comparison | Installed image tag is an ancestor of local `main` commit `ba562c11ad9c7d67db02499b4e60776ac9dbb336` (`git merge-base --is-ancestor`, exit 0). Since that tag, 34 files under `operations/fleet/fleet/server/web` or `shared/web` changed. |

Sanitized raw summary: `X:/DevTemp/rosy-site-uiux-current/readback.json`, SHA-256 `795d1dd463546965ba8eb674fc648e724e293c29f2191e1ad09444d65d4f1d6f`. The public record contains no private address, robot name, or credential.

This proves current discovery and installed image identity, not authenticated Fleet page rendering, robot or camera status readback, or the current candidate's layout on the site PC. The installed UI is behind the candidate, so its screen cannot satisfy the candidate's D-153 G2/G3 gate. The user's [operator walkthrough](../uiux-surfaces-2026-10-06/operator-walkthrough.md) and current-candidate installation/readback remain **HOLD**.
