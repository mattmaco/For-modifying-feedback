#!/usr/bin/env python3
"""Dump a .feedpak's current sections and parts (phrases) as a structure plan.

The output is the same YAML format tools/feedpak_structure.py applies, so the
usual loop is: extract -> edit the YAML -> apply.

Usage:
    python3 tools/feedpak_extract_structure.py SONG.feedpak [ARRANGEMENT] > plan.yaml
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from feedpak_structure import Grid  # noqa: E402


def main() -> None:
    pak = Path(sys.argv[1])
    arr_id = sys.argv[2] if len(sys.argv) > 2 else "lead"
    with zipfile.ZipFile(pak) as z:
        tl = json.loads(z.read("song_timeline.json"))
        arr = json.loads(z.read(f"arrangements/{arr_id}.json"))
    grid = Grid(tl["beats"])

    def pos(t: float) -> str:
        lab = grid.label(t)
        if lab.startswith("t"):
            return lab
        m, _, b = lab[1:].partition("+")
        # Only use the measure form when it reproduces the time exactly.
        cand = m + (f"+{b}" if b else "")
        return cand if abs(grid.time_of(cand) - t) < 0.0005 else f"t{t:.3f}"

    secs = sorted(tl["sections"], key=lambda s: s["time"])
    starts = sorted(p["start_time"] for p in arr.get("phrases", []))
    print(f"# extracted from {pak.name} ({arr_id})")
    print(f"phrase_arrangements: [{arr_id}]" if starts else "phrase_arrangements: []")
    print("sections:")
    for i, s in enumerate(secs):
        end = secs[i + 1]["time"] if i + 1 < len(secs) else float("inf")
        inside = [t for t in starts if s["time"] - 1e-3 <= t < end - 1e-3]
        on_start = bool(inside) and abs(inside[0] - s["time"]) < 1e-3
        parts = inside[1:] if on_start else inside
        print(f"  - name: {s['name']}")
        print(f'    at: "{pos(s["time"])}"')
        if starts and not on_start:
            print("    phrase: false")
        if parts:
            print("    parts: [" + ", ".join(f'"{pos(t)}"' for t in parts) + "]")


if __name__ == "__main__":
    main()
