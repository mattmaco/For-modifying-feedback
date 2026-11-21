#!/usr/bin/env python3
"""Apply a section + part (phrase) plan to a .feedpak and write a new .feedpak.

Sections are the big song-structure markers (intro, riff_a, ...). Parts are the
smaller loopable chunks inside each section; feedBack stores them as `phrases`
in the arrangement JSON, and Section Practice offers them as Part 1, Part 2, ...
of whichever section you pick. See docs/feedpak-editing-guide.md.

The plan is a YAML file (see songs/*/structure.yaml):

    phrase_arrangements: [lead, bass]    # which charts get parts
    sections:
      - name: intro
        at: "3"                           # measure 3, on the downbeat
      - name: riff_a
        at: "4+3"                         # measure 4, beat offset 3 (= beat 4 in 4/4)
        parts: ["7", "9", "11"]           # more part starts inside this section
      - name: noguitar
        at: "t220.491"                    # absolute seconds
        phrase: false                     # marker only, do not start a part here

Positions: "M" = downbeat of measure M, "M+B" = B beats after it (B may be
fractional: "12+3.5" is the "and" of beat 4), "tSECONDS" = absolute time.
Every section start is also a part start unless `phrase: false`.

If a note sits a few milliseconds before a computed grid time, the boundary is
pulled back to that note so it is not cut off into the previous part.
Exact "t..." times are never moved. Set `snap_before: 0.01` (seconds) in the plan
to narrow that window for very fast music, where a note just before the barline
is usually the end of the previous phrase rather than a pickup.

Usage:
    python3 tools/feedpak_structure.py IN.feedpak PLAN.yaml OUT.feedpak
    python3 tools/feedpak_structure.py IN.feedpak PLAN.yaml --dry-run
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "reference" / "feedpak-spec" / "schemas"
SNAP_BEFORE = 0.06  # seconds a note may sit before a grid boundary and still pull it back
SNAP_AFTER = 0.0


def dumps(obj) -> str:
    # Matches the compact style feedBack writes.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class Grid:
    def __init__(self, beats: list[dict]):
        self.times = [b["time"] for b in beats]
        self.bar_index = {b["measure"]: i for i, b in enumerate(beats) if b["measure"] > 0}

    def time_of(self, pos: str) -> float:
        pos = str(pos).strip()
        if pos.startswith("t"):
            return float(pos[1:])
        m, _, off = pos.partition("+")
        i = self.bar_index[int(m)]
        b = float(off) if off else 0.0
        whole = int(b)
        frac = b - whole
        j = i + whole
        t0 = self.times[j]
        if frac:
            t1 = self.times[j + 1] if j + 1 < len(self.times) else t0 + (t0 - self.times[j - 1])
            return t0 + frac * (t1 - t0)
        return t0

    def label(self, t: float) -> str:
        bars = sorted(self.bar_index.items(), key=lambda kv: kv[1])
        idxs = [i for _, i in bars]
        k = bisect.bisect_right([self.times[i] for i in idxs], t + 1e-6) - 1
        if k < 0:
            return f"t{t:.3f}"
        m, i = bars[k]
        j = bisect.bisect_right(self.times, t + 1e-6) - 1
        nxt = self.times[j + 1] if j + 1 < len(self.times) else self.times[j] + 0.5
        beat = (j - i) + (t - self.times[j]) / (nxt - self.times[j])
        return f"m{m}" + (f"+{beat:.2f}".rstrip("0").rstrip(".") if beat > 0.01 else "")


def onsets(arrs: dict[str, dict]) -> list[float]:
    out = []
    for a in arrs.values():
        out += [n["t"] for n in a.get("notes", [])]
        out += [c["t"] for c in a.get("chords", [])]
    return sorted(out)


def snap(t: float, ons: list[float], before: float = SNAP_BEFORE) -> float:
    lo = bisect.bisect_left(ons, t - before)
    cands = [o for o in ons[lo:] if o <= t + SNAP_AFTER]
    return round(min([t] + cands), 3)


def build_phrases(arr: dict, starts: list[float], song_end: float) -> list[dict]:
    """One phrase per start; single difficulty level holding everything in its window.

    The first phrase also takes anything before it and the last anything after it,
    so concatenating all levels always reproduces the full chart (the highway draws
    from the phrase levels once phrases exist, so a dropped note would vanish).
    """
    out = []
    for i, st in enumerate(starts):
        lo = float("-inf") if i == 0 else st
        hi = float("inf") if i == len(starts) - 1 else starts[i + 1]
        end = song_end if i == len(starts) - 1 else starts[i + 1]
        inw = lambda t: lo <= t < hi  # noqa: E731
        out.append({
            "start_time": round(st, 3),
            "end_time": round(end, 3),
            "max_difficulty": 0,
            "levels": [{
                "difficulty": 0,
                "notes": [n for n in arr.get("notes", []) if inw(n["t"])],
                "chords": [c for c in arr.get("chords", []) if inw(c["t"])],
                "anchors": [a for a in arr.get("anchors", []) if inw(a["time"])],
                "handshapes": [h for h in arr.get("handshapes", []) if inw(h["start_time"])],
            }],
        })
    return out


def insert_key_before(d: dict, key: str, value, before: tuple[str, ...]) -> dict:
    if key in d:
        d[key] = value
        return d
    out = {}
    placed = False
    for k, v in d.items():
        if not placed and k in before:
            out[key] = value
            placed = True
        out[k] = v
    if not placed:
        out[key] = value
    return out


def validate(name: str, obj, schema_file: str) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return [f"(jsonschema not installed; skipped {name})"]
    path = SCHEMAS / schema_file
    if not path.exists():
        return [f"(schema {schema_file} missing; skipped {name})"]
    schema = json.loads(path.read_text())
    v = jsonschema.Draft202012Validator(schema)
    return [f"{name}: {e.message} at {list(e.path)}" for e in v.iter_errors(obj)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("plan")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.dry_run and not a.out:
        ap.error("give OUT.feedpak or --dry-run")

    plan = yaml.safe_load(Path(a.plan).read_text())
    zin = zipfile.ZipFile(a.src)
    manifest = yaml.safe_load(zin.read("manifest.yaml"))
    tl_name = manifest.get("song_timeline", "song_timeline.json")
    tl = json.loads(zin.read(tl_name))
    arr_files = {x["id"]: x["file"] for x in manifest["arrangements"]}
    arrs = {k: json.loads(zin.read(f)) for k, f in arr_files.items()}
    song_end = float(manifest.get("duration") or tl["beats"][-1]["time"])

    grid = Grid(tl["beats"])
    ons = onsets(arrs)

    snap_before = float(plan.get("snap_before", SNAP_BEFORE))

    def place(pos) -> float:
        # Exact "t..." times are used as written; grid positions get snapped.
        t = grid.time_of(pos)
        return round(t, 3) if str(pos).strip().startswith("t") else snap(t, ons, snap_before)

    sections, phrase_starts, counts = [], [], {}
    for s in plan["sections"]:
        t = place(s["at"])
        counts[s["name"]] = counts.get(s["name"], 0) + 1
        sections.append({"name": s["name"], "number": s.get("number", counts[s["name"]]), "time": t})
        if s.get("phrase", True):
            phrase_starts.append((t, s["name"]))
        for p in s.get("parts") or []:
            phrase_starts.append((place(p), s["name"]))
    sections.sort(key=lambda x: x["time"])
    phrase_starts.sort()
    starts = [t for t, _ in phrase_starts]
    if len(set(starts)) != len(starts):
        print("ERROR: two parts start at the same time", file=sys.stderr)
        return 1

    # Report: each section with the parts Section Practice will offer inside it.
    def n_events(A: dict, lo: float, hi: float) -> int:
        return (sum(lo <= n["t"] < hi for n in A.get("notes", []))
                + sum(lo <= c["t"] < hi for c in A.get("chords", [])))

    print(f"{'time':>8}  {'pos':10} section / part   [events per chart]")
    for si, s in enumerate(sections):
        s_end = sections[si + 1]["time"] if si + 1 < len(sections) else float("inf")
        mine = [i for i, t in enumerate(starts) if s["time"] - 1e-6 <= t < s_end - 1e-6]
        print(f"{s['time']:8.3f}  {grid.label(s['time']):10} {s['name']} {s['number']}  ({len(mine)} parts)")
        for k, i in enumerate(mine, 1):
            hi = starts[i + 1] if i + 1 < len(starts) else float("inf")
            counts_str = ", ".join(f"{aid}: {n_events(A, starts[i], hi)}" for aid, A in arrs.items()
                                   if aid in plan.get("phrase_arrangements", []))
            print(f"{starts[i]:8.3f}  {grid.label(starts[i]):10}   part {k}  [{counts_str}]")

    if a.dry_run:
        return 0

    # Apply
    tl["sections"] = sections
    out_files = {tl_name: tl}
    problems = validate(tl_name, tl, "song-timeline.schema.json")
    for aid, A in arrs.items():
        if "sections" in A:
            A["sections"] = sections
        if aid in plan.get("phrase_arrangements", []):
            ph = build_phrases(A, starts, song_end)
            got = sum(len(p["levels"][0]["notes"]) for p in ph)
            gotc = sum(len(p["levels"][0]["chords"]) for p in ph)
            assert got == len(A.get("notes", [])) and gotc == len(A.get("chords", [])), "phrase coverage mismatch"
            A = insert_key_before(A, "phrases", ph, ("beats", "sections"))
        elif "phrases" in A and plan.get("drop_other_phrases"):
            del A["phrases"]
        out_files[arr_files[aid]] = A
        problems += validate(arr_files[aid], A, "arrangement.schema.json")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        if any(not p.startswith("(") for p in problems):
            return 1

    with zipfile.ZipFile(a.out, "w") as zout:
        for info in zin.infolist():
            data = dumps(out_files[info.filename]).encode() if info.filename in out_files else zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
