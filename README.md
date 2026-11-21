# For-modifying-feedback

Tools and notes for editing [feedBack](https://github.com/got-feedBack/feedBack) `.feedpak`
tabs. The main job is adding sections, and the parts inside each section that Section
Practice loops, so a song can be learned riff by riff.

| path | what |
|---|---|
| `docs/feedpak-editing-guide.md` | how sections and parts work in feedBack and the Song Editor, plus conventions |
| `reference/feedpak-spec/` | copy of the official feedpak spec and JSON schemas (CC0 / MIT, upstream commit `52548b7`) |
| `tools/feedpak_bars.py` | print an arrangement bar by bar (notes, chords, section and part markers) |
| `tools/feedpak_extract_structure.py` | dump a pack's sections and parts as an editable YAML plan |
| `tools/feedpak_structure.py` | apply a YAML plan to a pack and write a new `.feedpak` |
| `songs/*/structure.yaml` | the section and part plan for each song |

Songs:

- **Two Fish and an Elephant**: the reference layout, extracted from the user's `home_fix_v5` pack.
- **Dern Kala**: 11 descriptively named sections (Main Riff, 7th Fret Riff, Double Stop Sixths, ...)
  and 39 parts per chart (lead and bass). See the comments in `songs/dern-kala/structure.yaml`.

- **La Campanella (Liszt, arranged for guitar)**: generated from a piano MIDI by
  `songs/la-campanella/arrange.py` (reduction, fingering with tapping, FluidSynth nylon-guitar
  audio), then sectioned with `songs/la-campanella/structure.yaml`.

`.feedpak` and `.mid` files are git-ignored (song audio / third-party sequencing).
