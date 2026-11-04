# AGENTS.md

Guidance for coding agents working in this repo.

Canonical GitHub remote is `noomz/noomz-themes`. Do not push to `noomzopendream`.

## Project purpose

`noomz-themes` stores high-contrast light Modus Operandi themes for agent CLIs:

- Claude Code themes: `themes/claude/*.json`
- pi.dev themes: `themes/pi.dev/*.json`
- Hermes Agent themes: `themes/hermes/*.yaml`
- kitty themes: `themes/kitty/*.conf`

Keep palette changes consistent across supported CLIs when possible.

## Repo layout

```text
themes/
  claude/     Claude Code JSON themes
  pi.dev/     pi.dev JSON themes
  hermes/     Hermes YAML skins
  kitty/      kitty conf themes
scripts/
  install.sh
  validate-claude-theme.py
  palette-report.py        palette metrics + report generator
  fetch-recent-fonts.py    downloads post-2019 catalogue fonts -> .cache/recent-fonts, docs/fonts, docs/recent-fonts.json
  font-metrics.py          measures installed and --extra-fonts fonts -> docs/font-metrics.json
  font-report.py           scoring + report generator -> docs/font-report.html
  font-report-meta.json    prose and sources for the font report
```

## Validation

After changing Claude Code themes, run:

```sh
python3 scripts/validate-claude-theme.py themes/claude/*.json
```

For stricter CI-like validation, run:

```sh
python3 scripts/validate-claude-theme.py --strict-tokens themes/claude/*.json
```

After changing install behavior, run or inspect:

```sh
bash scripts/install.sh
```

Terminal config snippets in the report are generated, not written by hand. Their syntax is
version-sensitive (kitty dropped `adjust_line_height` in 0.49), so check the option against
the installed version's man page or docs before changing a snippet template, and record the
version in `terminal_versions` in `scripts/font-report-meta.json`.

After changing the font measurement or scoring, re-run both font scripts in order — the
report reads the JSON, not the font files:

```sh
python3 scripts/font-metrics.py --extra-fonts .cache/recent-fonts && python3 scripts/font-report.py
```

Omit `--extra-fonts` and the post-2019 test fonts drop out of the report. If
`.cache/recent-fonts` is missing, run `uv run scripts/fetch-recent-fonts.py` first.

The report's previews load `fonts/` relative to the report, because the hosted page's CSP
allows fonts only from its own origin. To refresh them from the existing manifest without
measuring anything, run `uv run scripts/fetch-recent-fonts.py --webfonts-only`, then
regenerate the report. Publish the reports and `fonts/`, not all of `docs/`: artifact-host
takes one 32 MiB tar per publish.

`docs/font-metrics.json` is generated and untracked. The report is only as current as
the last metrics run, so never edit the report's numbers by hand.

The leaderboard is built from three registries in `font-report.py`: `board_columns` (one
`Column` per column, with its sort value, cell, first-click direction and group),
`board_facets` (filter chips) and `BOARD_VIEWS` (named sort and filter presets). Add a column
or filter there, not in the row markup. The page's sort script is `BOARD_JS`. Its classes must
not reuse names from the palette report's stylesheet, which the font report loads too:
`.chip` is already a colour swatch there.

## Style rules

- Preserve existing theme names and slugs unless user explicitly asks for rename.
- Prefer exact documented token names for Claude Code theme overrides.
- Keep color values valid hex strings.
- Avoid broad palette rewrites unless requested; make small, traceable changes.
- When adding new variants, add matching README install/docs entries.
- Keep JSON/YAML formatting stable and human-readable.
- HTML tables in a generated report: build them through `font-report.py`'s `table()` helper,
  which runs `check_columns` and raises when a row's cell count differs from the header's.
  A row one cell short renders as a silently shifted table with a blank last column.
- Reports: never hand-edit a number in `docs/*.html`. Numbers come from the generator,
  and the generator reads measurements. Fix the measurement, then re-run.
- Never claim a font or palette reduces eye strain. The reports measure contrast,
  geometry and glyph properties and label each axis with what the literature supports.

## Safety notes

- Do not edit user home config files (`~/.claude`, `~/.pi`, `~/.hermes`) unless user asks.
- Do not kill terminal, Claude, pi, Hermes, cmux, or other running agent processes for theme reloads.
- Theme runtime smoke tests should use temporary obvious colors, then revert before finishing.
