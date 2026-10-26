"""The one-ssh-call host measurement remote_pytest.place() ranks on (D-568): PROBE and its parser.

Standard library only.
"""

from __future__ import annotations

# Free GB hard floor of ~/rosy-test's and /tmp's disk (rosy-ops lab-host-storage rule 1, 30 GiB, is the earlier agent
# pre-check). No percent rule: 90% of a 434-468 GB lab disk still leaves ~45 GB and would refuse healthy hosts.
DISK_FLOOR_GB = 20

# One line: ROSYPROBE nproc load1 avail_kb total_kb py312 sim busy lock_cores lock_gb site sim_held browser_jobs,
# then free_kb use% of ~/rosy-test's and /tmp's filesystems (df -Pk; absent from an older probe). Dead-pid
# locks and expired reservations (<expiry epoch> <class> <cores> <GB>) go; both count toward the budget, and
# sim_held counts the live ones of class sim (remote_sim, --pick sim, a hand-run Gazebo lock), browser_jobs the
# live browser job locks of every run (remote_job.JOB), so lanes stay under the per-host cap across runs.
PROBE = r"""J=~/rosy-jobs; c=0; m=0; g=0; w=0; now=$(date +%s)
for f in "$J"/*.resv; do
  [ -e "$f" ] || continue; read -r t k fc fm < "$f" || true
  case "$t$fc$fm" in ''|*[!0-9]*) rm -f "$f"; continue;; esac
  if [ "$t" -gt "$now" ]; then c=$((c+fc)); m=$((m+fm)); [ "$k" = sim ] && g=$((g+1)); else rm -f "$f"; fi
done
for f in "$J"/*.lock; do
  [ -e "$f" ] || continue; read -r pid k fc fm < "$f" || true
  case "$fc$fm" in ''|*[!0-9]*) fc=0 fm=0;; esac  # whole numbers only; never evaluate file text
  if kill -0 "$pid" 2>/dev/null; then c=$((c+${fc:-0})); m=$((m+${fm:-0})); [ "$k" = sim ] && g=$((g+1)); [ "$k" = browser ] && w=$((w+1))
  else rm -f "$f"; fi
done
py=0; for p in /usr/bin/python3 ~/.local/bin/python3.12; do
  "$p" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null && py=1 && break; done
s=0; [ -f /opt/ros/jazzy/share/ros_gz_sim/package.xml ] && [ -f /opt/ros/jazzy/share/nav2_bringup/package.xml ] && s=1
b=0; if [ -e "$J/busy" ]; then  # "<expiry epoch> <owner> <pid>" or a bare touch; 2 = pre-boot, 3 = expired
  b=1; t=; read -r t _ < "$J/busy" 2>/dev/null || true
  case "$t" in ''|*[!0-9]*) e=0;; *) e=${#t};; esac
  if [ "$e" -ge 10 ]; then [ "$t" -gt "$now" ] 2>/dev/null || b=3  # an explicit expiry wins over a reboot
  # The site PC's hold may be a person's equipment work, not a test job: a reboot never releases it (robot-4a).
  elif [ ! -e "$J/site" ] && [ "$(stat -c %Y "$J/busy")" -lt "$(awk '/^btime /{print $2}' /proc/stat)" ]; then b=2; fi
fi
st=0; [ -e "$J/site" ] && st=1
d=~/rosy-test; [ -d "$d" ] || d=~
echo "ROSYPROBE $(nproc) $(cut -d' ' -f1 /proc/loadavg)" \
  "$(awk '/^MemAvailable:/{a=$2} /^MemTotal:/{t=$2} END{print a, t}' /proc/meminfo) $py $s $b $c $m $st $g $w" \
  "$(df -Pk "$d" /tmp 2>/dev/null | awk 'NR>1{sub("%","",$5); printf "%s %s ", $4, $5}')"
"""


def parse_probe(out: str) -> dict | None:
    """The ROSYPROBE line of PROBE output (login-shell chatter around it is ignored), or None."""
    try:
        line = [ln for ln in out.splitlines() if ln.startswith("ROSYPROBE ")][-1]
        n, load, avail, total, py, sim, busy, cores, gb, site, held, browsers, *disk = line.split()[1:]
        p = {"nproc": int(n), "load1": float(load), "avail_gb": int(avail) / 2**20,
             "total_gb": int(total) / 2**20, "pytest": py == "1", "sim": sim == "1", "busy": busy == "1",
             "busy_ignored": {"2": "pre-boot", "3": "expired"}.get(busy),
             "lock_cores": int(cores), "lock_gb": int(gb), "site": site == "1",
             "sim_held": int(held), "browser_jobs": int(browsers)}
        free, use = [int(x) for x in disk[0::2]], [int(x) for x in disk[1::2]]
        if free and use:  # the fuller of the two filesystems; an older probe has none (unknown = ok)
            p["disk_free_gb"], p["disk_use"] = min(free) / 2**20, max(use)
        return p
    except (IndexError, ValueError):
        return None


def disk_full(p: dict) -> bool:
    """Below DISK_FLOOR_GB free; False when the probe did not measure the disk."""
    return "disk_free_gb" in p and p["disk_free_gb"] < DISK_FLOOR_GB
