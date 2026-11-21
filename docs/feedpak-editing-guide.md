# Editing feedpak tabs: sections and parts

Notes for editing `.feedpak` songs for [feedBack](https://github.com/got-feedBack/feedBack),
mainly how to add **sections** and the smaller **parts** inside them so a song
is easy to learn riff by riff.

Sources: the official format spec (copied into `reference/feedpak-spec/`, CC0/MIT),
plus reading the feedBack app and the Song Editor plugin
(`got-feedBack/feedBack`, `got-feedBack/feedBack-plugin-editor`, checked Nov 2026).
The app and editor code is not copied here: feedBack is AGPL and the editor repo
has no license file. The behaviour is summarised in my own words below.

---

## 1. What is inside a .feedpak

A `.feedpak` is a zip file:

| file | what it holds |
|---|---|
| `manifest.yaml` | title, artist, duration, list of arrangements and stems |
| `song_timeline.json` | the song's **beats**, **sections**, tempos, time signatures |
| `arrangements/lead.json`, `bass.json` | the notes, chords, anchors, handshapes, chord templates, and **phrases** (parts) for one instrument |
| `stems/full.ogg`, `preview.ogg`, `cover.png` | audio and art (never touched when editing structure) |

The JSON is written compactly (no spaces). Field names are short on purpose:
`t` time, `s` string (0 = lowest), `f` fret, `sus` sustain, `ho`/`po`
hammer-on/pull-off, `sl` slide-to fret, `bn` bend, `fg` finger. The full list
is in `reference/feedpak-spec/spec/feedpak-v1.md` §6.2.

## 2. Where structure lives

**Sections** are song-wide: the same markers apply to lead and bass.

```json
"sections": [{"name": "riff_a", "number": 1, "time": 10.831}, ...]
```

They live in `song_timeline.json`. Older packs also keep a copy inside the first
arrangement (`lead.json`). When both exist, `song_timeline.json` wins, but keep
the two identical anyway.

**Parts** are stored as `phrases`, one list per arrangement:

```json
"phrases": [
  {"start_time": 10.831, "end_time": 16.932, "max_difficulty": 0,
   "levels": [{"difficulty": 0, "notes": [...], "chords": [...], "anchors": [...], "handshapes": [...]}]}
]
```

`levels` exist for charts with several difficulty levels (the "mastery" slider).
Our songs have one level, so each phrase has a single level-0 entry holding a
copy of every note, chord, anchor and handshape in its time range.

## 3. How feedBack uses them (Section Practice)

- The practice bar lists sections. Labels come from the name: `_` becomes a
  space, trailing digits are dropped, and `intro, verse, chorus, bridge, solo,
  riff, outro` get standard capitals. Anything else is title-cased
  (`7th_fret_riff` shows as **7th Fret Riff 1**). The app numbers repeats itself,
  so don't put numbers at the end of a name.
- Only the plain names `intro, verse, chorus, bridge, solo, riff, outro` get a
  coloured chip in the practice bar. Descriptive names show in the default colour.
- **Back-to-back sections with the same name are merged** into one group
  (`solo`, `solo` = one "Solo" entry with the parts of both).
- When you pick a section, its **parts** are the phrases whose `start_time` falls
  inside that section. The first part is stretched back to the section start.
  With no phrases in that range, the whole section is one part.
- A synthetic "Start" section appears if notes come before the first marker.

**Important:** once an arrangement has `phrases`, the note highway draws from
the phrase levels, not from the main `notes` list. A note that is in `notes` but
in no phrase level **disappears from the highway**. Every note, chord, anchor
and handshape must be in exactly one phrase. `tools/feedpak_structure.py` checks
this. Also never write `"phrases": []`: leave the key out instead.

## 4. The Song Editor plugin

- `Shift+M` adds a section at the cursor and `Shift+P` adds a phrase (both are
  under the Add menu, in Markers). The editor names new phrases `phrase`, `phrase 2`, ...
- The editor does not author difficulty levels. On save it re-fills each
  phrase's levels from the flat note list using `start_time` up to the next
  phrase's `start_time`. Adding parts in the editor and saving gives the same
  result as the script here.
- Tempo-map edits move phrase `start_time` but not `end_time`. If you re-time a
  song in the editor, re-run the structure script to tidy the end times.

## 5. Conventions that make a song easy to learn

Taken from *Two Fish and an Elephant* (`songs/two-fish-and-an-elephant/structure.yaml`):

1. **Start on the pickup.** If a riff begins with lead-in notes before the
   barline, start the section (and its first part) on the first pickup note,
   so a loop always includes the lead-in.
2. **One part = one riff cycle.** That is usually 2 bars, or 1 bar for short
   answers or turnarounds. An 8-bar section usually splits into 4 parts.
3. **Name sections by what the guitar plays**, in plain words: `main_riff`,
   `raked_chords`, `sliding_melody`. Reuse a name only when the guitar part is
   really the same, so "Main Riff" always means the same thing to learn. If the
   bass repeats a riff but the guitar does something else, it gets a new name.
4. **Keep `noguitar` at the end** as a marker only, with no part starting there.
5. Fills and turnarounds stay inside the part they end, so the part loops
   musically.

## 6. Workflow with the tools in this repo

```bash
# 1. look at the song bar by bar (|> marks existing part starts)
python3 tools/feedpak_bars.py SONG.feedpak lead
python3 tools/feedpak_bars.py SONG.feedpak bass

# 2. dump the current structure as an editable plan
python3 tools/feedpak_extract_structure.py SONG.feedpak > songs/<song>/structure.yaml

# 3. edit the plan (positions are bar numbers: "12+3.5" = bar 12, the "and" of beat 4)

# 4. preview, then write a new pack (the original is never modified)
python3 tools/feedpak_structure.py SONG.feedpak songs/<song>/structure.yaml --dry-run
python3 tools/feedpak_structure.py SONG.feedpak songs/<song>/structure.yaml out/SONG_v2.feedpak
```

The structure script:

- converts bar/beat positions with the song's own beat grid
- pulls a boundary back to a note that sits up to 60 ms early, so a pickup is never cut off
- rewrites only `sections` (in `song_timeline.json` and `lead.json`) and `phrases`
- keeps every other zip entry byte-identical and in the same order
- validates against the JSON schemas in `reference/feedpak-spec/schemas/`

Requirements: Python 3, `pyyaml`, and optionally `jsonschema` for validation.
