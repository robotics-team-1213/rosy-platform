## D-919 - Passwordless fallback AP with authenticated Wi-Fi recovery

**Status:** Accepted (2026-10-29), following the user's explicit request for a passwordless recovery SSID when Pinky cannot connect. Device and field acceptance remain separate.

### Context

D-176 opens a per-device WPA2 fallback AP after the configured uplink fails. The operator requested a recovery network that can be joined without finding its AP password, then used to correct the configured SSID. An authenticated, AP-scoped HTTPS recovery service already exists; removing Wi-Fi encryption does not require removing its authorization.

### Decision

1. Add `ap.fallback_security: open|wpa2`, default `open`. This supersedes D-176 decision 4's WPA2 requirement only for `ap.mode: fallback`. Relay AP remains WPA2 and still requires its stored password; `off` remains off.
2. Keep the existing no-uplink grace, bounded AP window, STA retries, isolated-LAN recognition and radio/claim ownership. Open security does not keep the radio active during normal uplink operation.
3. An open NetworkManager profile omits the entire Wi-Fi security section. WPA2 retains its existing key handling. The fallback controller does not use an unused AP key or hand it to the display while open.
4. Publish the actual AP security in the local network status. The console and LCD show `No password` for open security; the Wi-Fi QR uses `T:nopass` and omits the password field. Missing security in old status retains WPA2 rendering. This narrowly supersedes D-176 decision 6's password display for open fallback.
5. Keep device identity, provisioning, CORE command authority, motor/mode guards, normal API authorization and the existing AP-only HTTPS recovery service unchanged. Recovery still requires its device certificate checks and one-time recovery code; joining the Wi-Fi network alone grants no setup or command authority.

### Deployment and compatibility

The controller/configuration/display changes are native payload updates, applied through the existing signed update and next-boot path. Deploy compatible consumers before enabling the new producer. Existing credentials remain valid for WPA2 and relay, and the provisioning schema does not change.

An existing image must first obtain the update before it understands the new configuration key. Do not insert that key into an older strict configuration parser or modify a signed base image. Passwordless fallback on the very first offline boot requires an official factory/native baseline containing this implementation.

### Verification and acceptance

Host tests cover default and explicit policies, malformed-policy refusal, keyfile security sections, stale-key omission, WPA2/relay compatibility, configuration application and unchanged timers/locks. The existing recovery authentication and transaction suites remain required. Host results do not establish an actual AP, phone connection, LCD readability, reboot or OTA acceptance; those need device evidence.
