#!/usr/bin/env python3
"""Print a bar-by-bar map of one arrangement in a .feedpak.

Each line is one measure: its number, start time, any section marker that falls
in it, and every note/chord as `beat=string:fret`. Beats count from 0 at the
barline (so `3.50` is the "and" of beat 4 in 4/4). Strings are 0 = lowest.

Suffixes: h hammer-on, p pull-off, /N slide to fret N, b bend.
Chords show as [TemplateName] ([ ] when the template has no name).
Phrase starts (the "parts" Section Practice loops) are marked with `|>`.

Usage:
    python3 tools/feedpak_bars.py SONG.feedpak            # lead
    python3 tools/feedpak_bars.py SONG.feedpak bass
"""
from __future__ import annotations

import bisect
import json
import sys
import zipfile
from pathlib import Path


def load(pak: Path, name: str):
    if pak.is_dir():
        return json.loads((pak / name).read_text())
    with zipfile.ZipFile(pak) as z:
        return json.loads(z.read(name))


def main() -> None:
    pak = Path(sys.argv[1])
    arr_id = sys.argv[2] if len(sys.argv) > 2 else "lead"
    tl = load(pak, "song_timeline.json")
    arr = load(pak, f"arrangements/{arr_id}.json")

    beats = [b["time"] for b in tl["beats"]]
    bars = [(i, b["time"], b["measure"]) for i, b in enumerate(tl["beats"]) if b["measure"] > 0]
    secs = [(s["time"], f'{s["name"]} {s.get("number", "")}'.strip()) for s in tl["sections"]]
    phrase_starts = [p["start_time"] for p in arr.get("phrases", [])]
    tnames = {i: (t.get("name") or " ") for i, t in enumerate(arr.get("templates", []))}

    events = []
    for n in arr.get("notes", []):
        lab = f'{n["s"]}:{n["f"]}'
        if n.get("ho"):
            lab += "h"
        if n.get("po"):
            lab += "p"
        if n.get("sl", -1) >= 0:
            lab += f'/{n["sl"]}'
        if n.get("bn"):
            lab += "b"
        events.append((n["t"], lab))
    for c in arr.get("chords", []):
        events.append((c["t"], f'[{tnames.get(c["id"], c["id"])}]'))
    for t in phrase_starts:
        events.append((t - 1e-6, "|>"))
    events.sort()

    def beat_pos(t: float) -> float:
        i = bisect.bisect_right(beats, t) - 1
        if i < 0:
            return float(i)
        nxt = beats[i + 1] if i + 1 < len(beats) else beats[i] + (beats[i] - beats[i - 1])
        return i + (t - beats[i]) / (nxt - beats[i])

    for k, (bi, t, m) in enumerate(bars):
        t1 = bars[k + 1][1] if k + 1 < len(bars) else float("inf")
        mark = ", ".join(name for st, name in secs if t - 1e-3 <= st < t1 - 1e-3)
        items = [f"{beat_pos(et) - bi:.2f}={lab}" for et, lab in events if t - 1e-3 <= et < t1 - 1e-3]
        print(f"m{m:3d} {t:8.3f}  {mark:16s}| " + " ".join(items))


if __name__ == "__main__":
    main()
