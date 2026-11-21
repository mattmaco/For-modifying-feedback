#!/usr/bin/env python3
"""Arrange Liszt's La Campanella (piano MIDI) for solo guitar and build a .feedpak.

Pipeline:
  1. Read the piano MIDI (quantized, 6/8, 1 bar = 1.5 s).
  2. Transpose up a semitone (G# minor -> A minor) so the bell note D#6 becomes E6,
     the 24th fret of the high E string. Fold anything outside the guitar range
     (E2..E6) by octaves.
  3. Reduce each onset to at most 4 notes: the top voice (melody / bell), the
     bass, and up to two inner notes.
  4. Pick a string/fret for every note with a dynamic-programming search that keeps
     the fretting hand inside a 5-fret box and minimises shifts. A top note that
     will not fit in the box is tapped (tp) by the picking hand. Fast same-string
     neighbours become hammer-ons / pull-offs (trills, turns).
  5. Render the guitar part (not the piano) with FluidSynth + FluidR3 nylon guitar,
     so the audio matches the chart exactly.
  6. Write manifest, song_timeline (6/8 grid, eighth-note beats), lead.json, audio,
     preview and cover into a .feedpak. Sections/parts are added afterwards with
     tools/feedpak_structure.py and songs/la-campanella/structure.yaml.

Usage:
    python3 songs/la-campanella/arrange.py LISZT.mid OUT_DIR
"""
from __future__ import annotations

import itertools
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import mido

SF2 = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
OPEN = [40, 45, 50, 55, 59, 64]          # E2 A2 D3 G3 B3 E4, string 0 = low E
MAX_FRET = 24
LO, HI = OPEN[0], OPEN[5] + MAX_FRET     # 40..88
TRANSPOSE = 1
OFFSET = 3.0                             # two 6/8 bars of count-in before the music
BAR = 1.5                                # seconds per 6/8 bar in the source MIDI
EIGHTH = BAR / 6
BOX = 5                                  # max fret span for the fretting hand
MERGE_TICKS = 8                          # onsets this close are one gesture (rolled chords)


# ---------------------------------------------------------------- 1. read MIDI
def read_midi(path):
    m = mido.MidiFile(path)
    tpb = m.ticks_per_beat
    sec_per_tick = 0.5 / tpb             # file is a constant 120 qpm
    t, held, notes = 0, {}, []
    for msg in mido.merge_tracks(m.tracks):
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            held.setdefault(msg.note, []).append(t)
        elif msg.type in ("note_off", "note_on") and held.get(msg.note):
            s = held[msg.note].pop(0)
            notes.append((s, t - s, msg.note))
    notes.sort()
    return notes, sec_per_tick


def fold(p):
    while p < LO:
        p += 12
    while p > HI:
        p -= 12
    return p


# ---------------------------------------------------------------- 2-3. reduce
def reduce_clusters(notes, spt):
    clusters, cur = [], []
    for s, d, p in notes:
        if cur and s - cur[0][0] > MERGE_TICKS:
            clusters.append(cur)
            cur = []
        cur.append((s, d, p))
    if cur:
        clusters.append(cur)

    out = []
    for c in clusters:
        t = c[0][0] * spt + OFFSET
        durs = {}
        for s, d, p in c:
            q = fold(p + TRANSPOSE)
            durs[q] = max(durs.get(q, 0), d * spt)
        pitches = sorted(durs)
        top, bass = pitches[-1], pitches[0]
        inner = [p for p in pitches[1:-1]]
        # prefer inner notes with new pitch classes, spread out
        keep = {top, bass}
        pcs = {top % 12, bass % 12}
        for p in sorted(inner, key=lambda p: (p % 12 in pcs, -p)):
            if len(keep) >= 4:
                break
            if p % 12 not in pcs:
                keep.add(p)
                pcs.add(p % 12)
        ps = sorted(keep)
        out.append({"t": round(t, 4), "pitches": ps, "dur": {p: durs[p] for p in ps}, "top": top})
    return out


# ---------------------------------------------------------------- 4. fingering
TAP_COST = 3.0


def s_ok_for_tap(frets):
    # a tapped top note must sit above everything the fretting hand holds
    rest = [f for f in frets[:-1] if f > 0]
    return not rest or (frets[-1] > max(rest) and max(rest) - min(rest) <= BOX - 1)


def candidates(ps):
    """All ways to place ascending pitches on ascending strings, with cost."""
    res = []
    n = len(ps)
    for strings in itertools.combinations(range(6), n):
        frets = [p - OPEN[s] for p, s in zip(ps, strings)]
        if any(f < 0 or f > MAX_FRET for f in frets):
            continue
        fretted = [f for f in frets if f > 0]
        tap = -1
        if fretted and max(fretted) - min(fretted) > BOX - 1:
            # allow the top note to be tapped if the rest fits in the box
            rest = [f for f in frets[:-1] if f > 0]
            if frets[-1] > 0 and strings[-1] >= 3 and (not rest or max(rest) - min(rest) <= BOX - 1) \
                    and (not rest or frets[-1] > max(rest)):
                tap = n - 1
                fretted = rest
            else:
                continue
        variants = [(tap, fretted)]
        # Optional tapping of a high top note even when the box would allow fretting it,
        # so the fretting hand can stay low while the picking hand rings the bell.
        if tap < 0 and frets[-1] >= 12 and strings[-1] >= 3 and s_ok_for_tap(frets):
            variants.append((n - 1, [f for f in frets[:-1] if f > 0]))
        for tp, fr in variants:
            span = (max(fr) - min(fr)) if fr else 0
            anchor = min(fr) if fr else None
            cost = 0.25 * span + 0.015 * sum(frets) - 0.15 * frets.count(0)
            if tp >= 0:
                cost += TAP_COST + (0 if frets[-1] >= 17 else 2.0)
            res.append({"strings": strings, "frets": frets, "tap": tp, "anchor": anchor,
                        "cost": cost, "hi": max(fr) if fr else 0})
    res.sort(key=lambda c: c["cost"])
    return res[:20]


def finger(clusters):
    cands = [candidates(c["pitches"]) for c in clusters]
    for i, cs in enumerate(cands):
        if not cs:  # should not happen after folding; fall back to dropping inner notes
            c = clusters[i]
            c["pitches"] = [c["pitches"][0], c["pitches"][-1]] if len(c["pitches"]) > 1 else c["pitches"]
            cands[i] = candidates(c["pitches"]) or candidates([c["pitches"][-1]])
            c["pitches"] = c["pitches"] if candidates(c["pitches"]) else [c["pitches"][-1]]

    INF = float("inf")
    # state: (anchor carried forward) ; dp over candidate index
    prev_cost = [cs["cost"] for cs in cands[0]]
    prev_anchor = [cs["anchor"] for cs in cands[0]]
    back = []
    for i in range(1, len(clusters)):
        gap = clusters[i]["t"] - clusters[i - 1]["t"]
        w = 1.0 if gap >= 0.4 else (1.8 if gap >= 0.15 else 3.0)
        cur_cost, cur_anchor, bp = [], [], []
        for c in cands[i]:
            best, arg, anc = INF, 0, None
            for j, pc in enumerate(prev_cost):
                a0 = prev_anchor[j]
                a1 = c["anchor"]
                move = 0 if a0 is None or a1 is None else abs(a1 - a0)
                # the fretting hand must also reach the highest fretted note
                if a0 is not None and a1 is None and c["hi"] == 0:
                    move = 0
                v = pc + c["cost"] + w * move
                if v < best:
                    best, arg = v, j
                    anc = a1 if a1 is not None else a0
            cur_cost.append(best)
            cur_anchor.append(anc)
            bp.append(arg)
        back.append(bp)
        prev_cost, prev_anchor = cur_cost, cur_anchor
    k = min(range(len(prev_cost)), key=lambda j: prev_cost[j])
    choice = [k]
    for bp in reversed(back):
        k = bp[k]
        choice.append(k)
    choice.reverse()
    return [cands[i][k] for i, k in enumerate(choice)]


# ---------------------------------------------------------------- build chart
NOTE_DEFAULTS = {"sus": 0.0, "sl": -1, "slu": -1, "bn": 0.0, "ho": False, "po": False, "hm": False,
                 "hp": False, "pm": False, "mt": False, "tr": False, "ac": False, "tp": False,
                 "ln": False, "vb": False, "fhm": False, "plk": False, "slp": False, "rh": -1,
                 "pkd": -1, "ig": False}


def build(clusters, fing):
    # flatten to per-string events
    events = []
    for c, f in zip(clusters, fing):
        for idx, (s, fr) in enumerate(zip(f["strings"], f["frets"])):
            p = OPEN[s] + fr
            events.append({"t": c["t"], "s": s, "f": fr, "p": p, "tap": idx == f["tap"],
                           "dur": c["dur"][p], "top": p == c["top"], "anchor": f["anchor"]})
    events.sort(key=lambda e: (e["t"], e["s"]))
    # cap sounding length at the next note on the same string; legato marks
    last_on_string = {}
    by_string = {}
    for e in events:
        by_string.setdefault(e["s"], []).append(e)
    for s, evs in by_string.items():
        for a, b in zip(evs, evs[1:]):
            a["dur"] = min(a["dur"], b["t"] - a["t"])
        for a, b in zip(evs, evs[1:]):
            gap = b["t"] - a["t"]
            if 0 < gap <= 0.14 and a["f"] > 0 and b["f"] > 0 and a["f"] != b["f"] \
                    and abs(a["f"] - b["f"]) <= 4 and not b["tap"] and not a["tap"]:
                b["legato"] = "ho" if b["f"] > a["f"] else "po"
    del last_on_string

    notes, chords, templates, tmpl_idx = [], [], [], {}
    groups = {}
    for e in events:
        groups.setdefault(e["t"], []).append(e)

    def note_obj(e, with_t):
        n = {"t": e["t"]} if with_t else {}
        n.update({"s": e["s"], "f": e["f"]})
        n.update(NOTE_DEFAULTS)
        sus = e["dur"] if e["dur"] >= 0.45 else 0.0
        n["sus"] = round(sus, 3)
        n["tp"] = e["tap"]
        if e.get("legato") == "ho":
            n["ho"] = True
        elif e.get("legato") == "po":
            n["po"] = True
        return n

    for t in sorted(groups):
        g = groups[t]
        if len(g) == 1:
            notes.append(note_obj(g[0], True))
            continue
        frets = [-1] * 6
        for e in g:
            frets[e["s"]] = e["f"]
        key = tuple(frets)
        if key not in tmpl_idx:
            tmpl_idx[key] = len(templates)
            templates.append({"name": "", "displayName": "", "arp": False,
                              "fingers": [-1] * 6, "frets": list(frets)})
        chords.append({"t": t, "id": tmpl_idx[key], "hd": False,
                       "notes": [note_obj(e, False) for e in sorted(g, key=lambda e: e["s"])]})

    # anchors: where the fretting hand sits
    anchors, last = [], None
    for c, f in zip(clusters, fing):
        a = f["anchor"]
        if a is None or a == last:
            continue
        anchors.append({"time": c["t"], "fret": max(1, a), "width": 4 if f["hi"] - a <= 3 else 5})
        last = a
    return events, notes, chords, templates, anchors


# ---------------------------------------------------------------- 5. audio
def write_midi(events, path):
    mid = mido.MidiFile(ticks_per_beat=960)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))
    tr.append(mido.Message("program_change", program=24, channel=0))   # nylon guitar
    tr.append(mido.Message("control_change", control=91, value=40, channel=0))  # reverb
    tr.append(mido.Message("control_change", control=7, value=118, channel=0))
    to_tick = lambda s: int(round(s * 1920))  # 120 qpm, 960 tpb -> 1920 ticks/s
    msgs = []
    for e in events:
        vel = 96 if e["tap"] else (88 if e["top"] else (80 if e["s"] <= 1 else 68))
        if e.get("legato"):
            vel -= 14
        dur = max(0.09, min(e["dur"], 4.0))
        msgs.append((to_tick(e["t"]), 1, mido.Message("note_on", note=e["p"], velocity=vel, channel=0)))
        msgs.append((to_tick(e["t"] + dur) - 1, 0, mido.Message("note_off", note=e["p"], velocity=0, channel=0)))
    msgs.sort(key=lambda x: (x[0], x[1]))
    now = 0
    for tick, _, msg in msgs:
        msg.time = max(0, tick - now)
        now = max(now, tick)
        tr.append(msg)
    mid.save(path)


def render(mid_path, out_dir, song_end):
    wav = out_dir / "full.wav"
    subprocess.run(["fluidsynth", "-ni", "-g", "0.7", "-r", "44100", "-F", str(wav), SF2, str(mid_path)],
                   check=True, capture_output=True)
    full = out_dir / "full.ogg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-t", f"{song_end:.3f}",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100",
                    "-c:a", "libvorbis", "-q:a", "6", str(full)], check=True)
    prev = out_dir / "preview.ogg"
    # preview: the bell theme with bass (source bars 13-20)
    start = OFFSET + 12 * BAR
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", "30", "-i", str(full),
                    "-af", "afade=t=in:d=1,afade=t=out:st=27:d=3", "-c:a", "libvorbis", "-q:a", "4", str(prev)],
                   check=True)
    wav.unlink()
    return full, prev


def cover(path):
    from PIL import Image, ImageDraw, ImageFont
    W = 512
    im = Image.new("RGB", (W, W), (20, 18, 30))
    d = ImageDraw.Draw(im)
    for r in range(240, 0, -6):  # soft glow
        c = int(20 + (240 - r) * 0.25)
        d.ellipse((W / 2 - r, 190 - r * 0.8, W / 2 + r, 190 + r * 0.8), fill=(c + 10, c, int(c * 0.6) + 20))
    # bell
    gold = (226, 184, 92)
    d.polygon([(256, 95), (215, 120), (196, 230), (178, 262), (334, 262), (316, 230), (297, 120)], fill=gold)
    d.ellipse((240, 258, 272, 290), fill=gold)
    d.rectangle((250, 78, 262, 98), fill=gold)
    try:
        f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", 52)
        f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 26)
    except OSError:
        f1 = f2 = ImageFont.load_default()
    d.text((W / 2, 360), "La Campanella", font=f1, fill=(240, 232, 214), anchor="mm")
    d.text((W / 2, 412), "Liszt · for solo guitar", font=f2, fill=(200, 190, 170), anchor="mm")
    im.save(path)


# ---------------------------------------------------------------- 6. pack
def main():
    src, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    work = out_dir / "la-campanella-build"
    work.mkdir(parents=True, exist_ok=True)

    raw, spt = read_midi(src)
    clusters = reduce_clusters(raw, spt)
    fing = finger(clusters)
    events, notes, chords, templates, anchors = build(clusters, fing)

    last_end = max(e["t"] + max(e["dur"], 0.5) for e in events)
    n_bars = math.ceil((last_end + 2.0) / BAR)
    song_end = n_bars * BAR

    beats = []
    for b in range(n_bars):
        for k in range(6):
            beats.append({"time": round(b * BAR + k * EIGHTH, 3), "measure": b + 1 if k == 0 else -1})
    timeline = {"version": 1, "beats": beats,
                "sections": [{"name": "noguitar", "number": 1, "time": round(last_end + 0.5, 3)}],
                "tempos": [{"time": 0.0, "bpm": 240.0}],
                "time_signatures": [{"time": 0.0, "ts": [6, 8]}]}

    lead = {"name": "Lead", "tuning": [0] * 6, "capo": 0, "notes": notes, "chords": chords,
            "anchors": anchors, "handshapes": [], "templates": templates,
            "tones": {"base": "Nylon", "changes": [], "definitions": []},
            "beats": beats, "sections": timeline["sections"]}

    mid_path = work / "guitar.mid"
    write_midi(events, mid_path)
    full, prev = render(mid_path, work, song_end)
    cover(work / "cover.png")

    manifest = f"""feedpak_version: 1.14.0
title: La Campanella (Guitar Arrangement)
artist: Franz Liszt
album: Grandes etudes de Paganini, S. 141 No. 3
year: 1851
duration: {song_end:.3f}
arrangements:
- id: lead
  name: Lead
  file: arrangements/lead.json
  tuning: [0, 0, 0, 0, 0, 0]
  capo: 0
  type: guitar
stems:
- id: full
  file: stems/full.ogg
  default: true
song_timeline: song_timeline.json
preview: preview.ogg
cover: cover.png
"""
    pak = out_dir / "Liszt_-_La_Campanella_guitar_nostructure.feedpak"
    dumps = lambda o: json.dumps(o, separators=(",", ":"))
    with zipfile.ZipFile(pak, "w") as z:
        z.write(work / "cover.png", "cover.png")
        z.writestr("manifest.yaml", manifest, compress_type=zipfile.ZIP_DEFLATED)
        z.write(prev, "preview.ogg")
        z.writestr("song_timeline.json", dumps(timeline), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("arrangements/lead.json", dumps(lead), compress_type=zipfile.ZIP_DEFLATED)
        z.write(full, "stems/full.ogg")

    taps = sum(e["tap"] for e in events)
    leg = sum(1 for e in events if e.get("legato"))
    print(f"source notes {len(raw)} -> guitar notes {len(events)} ({len(notes)} single, {len(chords)} chords), "
          f"{len(templates)} chord shapes, {taps} taps, {leg} hammer/pull, {len(anchors)} position shifts")
    print(f"length {song_end:.1f}s, {n_bars} bars (2 count-in)")
    print(f"wrote {pak}")


if __name__ == "__main__":
    main()
