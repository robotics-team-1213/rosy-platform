# Isolated Coupled Simulation Site (`rosy-sim-site`)

Parallel Docker Compose stack for running coupled simulation (`sim-fleet`, `sim-controller`, Read-Only `sim-world`, and optional `sim-light-core`) alongside `deploy/site` without port, network, or volume collisions.

## Isolation Guarantees

- **Compose project**: `rosy-sim-site`
- **Network & volumes**: `sim_backend`, `sim_fleet_data` (`sim-world` uses `tmpfs` `/var/lib/rosy-sim-world/worlds`, `sim-controller` pushes via HTTP to `http://world:18140`; never `site_backend`)
- **Loopback-only host ports**:
  - `sim-fleet`: `127.0.0.1:18090` -> container `8080`
  - `sim-world`: `127.0.0.1:18140` -> container `18140` (strictly Read-Only: `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`, `world_id=coupled-sim`)
  - `sim-controller`: `127.0.0.1:18190` -> container `18190`
  - `sim-light-core` (`light-core` profile): `127.0.0.1:18095` -> container `18095`

## AI PC + Model PC Split

Run the simulation stack (`sim-fleet`, `sim-controller`, `sim-world`) on the **AI PC** and point `ROSY_SIM_AI_URL` (via untracked `.env`) at the **Model PC** inference endpoint (default `http://host.docker.internal:11434`, model `ROSY_SIM_CONVERSATION_MODEL=qwen3-vl:8b-instruct`).

## Bring-Up

1. Copy `.env.example` to an untracked `.env` and populate `ROSY_SIM_REGISTRY_TOKEN`, `ROSY_SIM_CONFIG_DIR`, and `ROSY_SIM_WORLD_BUNDLE_DIR` (pre-built bundle with `data/`).
2. Start the core coupled sim stack (with external Gazebo + MuJoCo runners):
   ```bash
   docker compose --env-file .env -f deploy/sim_site/compose.yaml up -d
   ```
3. Or include the virtual 6-robot CORE simulator (`sim-light-core`) for headless loop verification:
   ```bash
   docker compose --env-file .env -f deploy/sim_site/compose.yaml --profile light-core up -d
   ```
