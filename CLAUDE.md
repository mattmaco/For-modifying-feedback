# For-modifying-feedback

Workspace for editing feedBack `.feedpak` song tabs. Most requests add or improve
**sections** and **parts** (`phrases`) so songs are easier to learn riff by riff.

Read `docs/feedpak-editing-guide.md` first. The format spec is in
`reference/feedpak-spec/spec/feedpak-v1.md`, with JSON schemas in `reference/feedpak-spec/schemas/`.

## How to work on a song

1. Unzip nothing by hand. Run `python3 -I tools/feedpak_bars.py SONG.feedpak lead`
   (and `bass`) to see every bar, then work out where the riffs repeat.
2. Write `songs/<song-slug>/structure.yaml` (same format as the existing ones), or start from
   `tools/feedpak_extract_structure.py`.
3. Check with `tools/feedpak_structure.py IN PLAN --dry-run`, then write to `out/`.
4. Hand the new `.feedpak` to the user. Never overwrite their original upload.

## Rules

- `songs/two-fish-and-an-elephant/structure.yaml` is the user's reference for good structure:
  sections start on pickup notes, and each part is one riff cycle (usually 2 bars).
- Every note, chord, anchor and handshape must land in exactly one phrase level, or it
  vanishes from the highway. The script asserts this.
- Never emit `"phrases": []`. Omit the key instead.
- Keep `song_timeline.json` sections and `lead.json` sections identical.
- `.feedpak` files hold copyrighted audio and are git-ignored. Commit plans and tools, not packs.
- Strings are numbered from 0 = low E. The bars tool prints `beat=string:fret`, with beats from 0.
