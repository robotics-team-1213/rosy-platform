"""Generate shared/web/cell-site-map.json (rosy.cell-site-map.v1): the one list of cell places (yard, temporary A/B, stand).

Zones, arms, not-places and aliases are the constants below; the yard and temporary places and their sim names come from the MuJoCo-free
`omx_two_arm_sites.Layout` and the r08 slots.json tier records. No coordinates: boxes live in cell-layout.json. Everything is planned_unverified (D-280).
Usage: python tools/sim/export_site_map.py [--out PATH] [--check]   (--check exits 1 when the file differs from a fresh export)
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import omx_two_arm_sites as sites  # noqa: E402

OUT = HERE.parents[1] / "shared/web/cell-site-map.json"
STATUS = "planned_unverified"
# Zone ids and the Korean names people read (term source: harborlogi CONTEXT; verdict 2026-11-17).
ZONES = (("yard", "장치 야드", "보관"), ("temp_a", "임시 장치 A", "임시"), ("temp_b", "임시 장치 B", "임시"), ("stand", "반출대", "반출"))
STAND_ARMS = ["arm_a"]  # user, 2026-11-17: the stand is reached by arm A only
NOT_PLACES = (("belt", "공급 경로"), ("supply_s", "공급 작업대 S"), ("ship_stern", "선미"), ("ship_bow", "선수"), ("vehicle_tray", "이송 차량 짐칸"))
# station_zones.yaml ids (values and API unchanged there); null = no place in this map
LEGACY_STATION_ZONES = {"EXP_S1": "stand:r1-s1", "EXP_S5_PALLET": "stand:r1-s1", "EXP_S3_BELT": "not_places:belt", "STG_C2": None, "STG_S3_WAIT": None}


def build_zones(L):
    """Zones in schema shape: slot `yard:r1-s1`, tier `yard:r1-s1-t1`, tier item = sim site name or null.
    Hold numbers are Harbor's (columns 1-3 = hold 1), never read from the sim's ship-h<k> names."""
    recs = {r["id"]: r for r in json.loads((sites.SHIP_ASSETS / "slots.json").read_text(encoding="utf-8"))["tier_records"]}
    # Harbor row 1 is the lowest ship y = highest fixture y = the arm_b side (computed from the records, not typed)
    ys = sorted({r["y_mm"] for r in recs.values()})
    yard, temp, by_stack = [], {"a": [], "b": []}, {}
    for name, s in L.sites.items():
        if s["kind"] in ("ship", "temp") and "stack" in s:
            by_stack.setdefault(s["stack"], {})[s["layer"]] = (name, s)
    for stack, layers in sorted(by_stack.items()):
        first = layers[0][1]
        if first["kind"] == "temp":
            sid = f"temp_{first['plate']}:r{first['lane']}-s1"
            temp[first["plate"]].append(dict(id=sid, label=f"{first['lane']}번", row=first["lane"], slot=1, columns=[1, 3],
                                             tiers=[dict(tier=k + 1, id=f"{sid}-t{k + 1}", item=layers[k][0]) for k in sorted(layers)]))
            continue
        ids = first["slots"]
        if not ids:
            continue  # stern bay: not a yard place
        cells = [recs[i] for i in ids]
        cols = sorted((int(r["bay"]) + 1) // 2 for r in cells)
        row = ys.index(cells[0]["y_mm"]) + 1
        arms = sorted(set.intersection(*[{"arm_" + a.lower() for a in r["arms"]} for r in cells]))
        slot = (cols[0] - 1) // 3 + 1
        sid = f"yard:r{row}-s{slot}"
        yard.append(dict(id=sid, label=f"{row}행 {cols[0]}~{cols[-1]}열", row=row, slot=slot, columns=[cols[0], cols[-1]], hold=slot, arms=arms,
                         physical=list(ids), tiers=[dict(tier=k + 1, id=f"{sid}-t{k + 1}", item=layers[k][0]) for k in sorted(layers)]))
    yard.sort(key=lambda z: (z["row"], z["slot"]))
    for v in temp.values():
        v.sort(key=lambda z: z["row"])
    zones = [dict(id="yard", label="장치 야드", role="보관", grid=dict(rows=3, columns=6, tiers=sites.R08_TIERS), slot_cells=3, slots=yard,
                  hold_boundary=dict(columns=[3, 4])),
             *[dict(id=f"temp_{t}", label=f"임시 장치 {t.upper()}", role="임시", grid=dict(rows=3, columns=3, tiers=sites.TEMP_TIERS), slot_cells=3,
                    slots=[dict(z, arms=[L.plates[t]["arm"]]) for z in temp[t]]) for t in "ab"],
             dict(id="stand", label="반출대", role="반출", grid=dict(rows=1, columns=3, tiers=1), slot_cells=3,
                  slots=[dict(id="stand:r1-s1", label="반출대", row=1, slot=1, columns=[1, 3], arms=STAND_ARMS,
                              tiers=[dict(tier=1, id="stand:r1-s1-t1", item=None)])])]
    for z in zones:
        z["arms"] = sorted({a for s in z["slots"] for a in s["arms"]})
        z["status"] = STATUS
        for s in z["slots"]:
            s["status"] = STATUS
    return zones


def build_aliases(zones, L):
    slots = [s for z in zones for s in z["slots"]]
    legacy_sim = {t["item"]: t["id"] for s in slots for t in s["tiers"] if t["item"]}
    legacy_sim.update({n: "not_places:belt" for n, s in L.sites.items() if s["kind"] == "belt"})
    legacy_sim.update({n: "not_places:ship_stern" for n, s in L.sites.items() if s["kind"] == "ship" and not s["slots"]})
    legacy_sim.setdefault("ship-stern-l0", "not_places:ship_stern")  # the sim stopped listing the stern as a site on 11-17
    return dict(legacy_layout={(f"yard-r{s['row']}-c{s['columns'][0]}" if s["id"].startswith("yard:") else f"{s['id'].split(':')[0]}-{s['row']}"): s["id"]
                                  for s in slots},  # feat/cell-ar-twin ids before 11-17: yard-r1-c4, temp_a-2, stand-1
                legacy_sim=legacy_sim, legacy_station_zones=LEGACY_STATION_ZONES)


def export():
    L = sites.Layout()
    zones = build_zones(L)
    return dict(schema="rosy.cell-site-map.v1", revision=1, status=STATUS, tier_height_mm=round(L.box[2] * 1000.0, 3), zones=zones,
                not_places=[dict(id=i, label=l) for i, l in NOT_PLACES], aliases=build_aliases(zones, L))


def render():
    return json.dumps(export(), indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="exit 1 when --out differs from a fresh export")
    a = ap.parse_args(argv)
    out, text = Path(a.out), render()
    if a.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"{out} is out of date: run python tools/sim/export_site_map.py", file=sys.stderr)
            return 1
        return 0
    out.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())