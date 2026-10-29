# noomz-themes

High-contrast themes for agent CLIs.

Currently included for Claude Code, pi.dev, Hermes Agent, and kitty:

- `modus-operandi`
- `modus-operandi-tinted` (uses canonical `modus-operandi-tinted` palette values from https://protesilaos.com/emacs/modus-themes-colors)
- `kanagawa` (Kanagawa Lotus-inspired light adaptation)
- `kanagawa-wave` (Kanagawa Wave-inspired dark adaptation)
- `tokyo-night-day` (TokyoNight Day-inspired adaptation)
- `everforest-light` (Everforest Light Medium; failing roles lightness-repaired to 4.5:1 on `bg0`)
- `everforest-dark` (Everforest Dark Medium; grey1 `#939f97` lifted to 4.5:1 on `bg0`)
- `gruvbox-light` (Gruvbox light; gray, green, yellow, aqua lifted to 4.5:1 on `bg0`)
- `gruvbox-dark` (Gruvbox dark; gray `#9a8c7e` and red `#fb5440` lifted to 4.5:1 on `#282828`)
- `flexoki-light` (Flexoki light; yellow, green, cyan lifted to 4.5:1 on paper)
- `flexoki-dark` (Flexoki dark; red and blue lifted to 4.5:1 on base-950)
- `primer-light` (GitHub Primer light ANSI; blueBright and magentaBright lifted to 4.5:1 on canvas)
- `primer-dark` (GitHub Primer dark ANSI; gray `#757d89` lifted to 4.5:1 on canvas)
- `catppuccin-latte` (Catppuccin Latte; failing accents lightness-repaired to 4.5:1 on base)
- `catppuccin-frappe` (Catppuccin Frappé dark palette)
- `catppuccin-macchiato` (Catppuccin Macchiato dark palette)
- `catppuccin-mocha` (Catppuccin Mocha dark palette)
- `noomz-rose-pine` (Rosé Pine main dark palette)
- `noomz-rose-pine-moon` (Rosé Pine Moon dark palette)
- `noomz-rose-pine-dawn` (Rosé Pine Dawn light palette)
- `noomz-rose-pine-dawn-contrast` (higher-contrast Rosé Pine Dawn adaptation)

The palettes keep readability high while darkening low-contrast text where needed, especially collapsed-output hints, file/link paths, dim metadata, neutral borders, and selection surfaces.

Dark Catppuccin flavors keep the upstream accents. Dim and comment text uses the first of Overlay 2, Subtext 0, or Subtext 1 that reaches 4.5:1 on the base color, which is Overlay 2 in Frappé, Macchiato, and Mocha. Latte keeps Subtext 1 for dim text; accents that fail 4.5:1 on base are lightness-repaired (hue and saturation stay).

Other repaired ports use the same 0.004-step HLS lightness move as `docs/palette-report.html`. Faded/neutral ramps that were not a failing body, dim, or accent role stay upstream.

Palette sources:

- Modus: https://protesilaos.com/emacs/modus-themes-colors
- Kanagawa/Kawakawa adaptation: https://github.com/rebelot/kanagawa.nvim
- Tokyo Night Day: https://github.com/folke/tokyonight.nvim
- Everforest Light Medium: https://github.com/sainnhe/everforest/blob/master/palette.md
- Gruvbox: https://github.com/morhetz/gruvbox
- Flexoki: https://stephango.com/flexoki
- Catppuccin: https://github.com/catppuccin/palette
- GitHub Primer: https://github.com/primer/primitives
- Rosé Pine: https://rosepinetheme.com/

## Install

Run the installer to copy all supported themes into local agent config directories:

```sh
bash scripts/install.sh
```

Claude themes are copied to `~/.claude/themes/` and to every existing CCS profile under `~/.ccs/instances/*/themes/`.

### Claude Code

```sh
mkdir -p ~/.claude/themes
cp themes/claude/*.json ~/.claude/themes/
```

Then select one inside Claude Code:

```text
/theme modus-operandi
/theme modus-operandi-tinted
/theme kanagawa
/theme kanagawa-wave
/theme tokyo-night-day
/theme everforest-light
/theme everforest-dark
/theme gruvbox-light
/theme gruvbox-dark
/theme flexoki-light
/theme flexoki-dark
/theme primer-light
/theme primer-dark
/theme catppuccin-latte
/theme catppuccin-frappe
/theme catppuccin-macchiato
/theme catppuccin-mocha
/theme noomz-rose-pine
/theme noomz-rose-pine-moon
/theme noomz-rose-pine-dawn
/theme noomz-rose-pine-dawn-contrast
```

### pi.dev

Preferred custom theme location:

```sh
mkdir -p ~/.pi/agent/themes
cp themes/pi.dev/*.json ~/.pi/agent/themes/
```

Then set `theme` to one theme slug in `~/.pi/agent/settings.json`, for example `modus-operandi`, `kanagawa`, `kanagawa-wave`, `tokyo-night-day`, `everforest-light`, `everforest-dark`, `gruvbox-light`, `gruvbox-dark`, `flexoki-light`, `flexoki-dark`, `primer-light`, `primer-dark`, `catppuccin-latte`, `catppuccin-frappe`, `catppuccin-macchiato`, `catppuccin-mocha`, `noomz-rose-pine`, `noomz-rose-pine-moon`, `noomz-rose-pine-dawn`, or `noomz-rose-pine-dawn-contrast`.

### Hermes Agent

```sh
mkdir -p ~/.hermes/skins
cp themes/hermes/*.yaml ~/.hermes/skins/
```

Then select one inside Hermes:

```text
/skin modus-operandi
/skin modus-operandi-tinted
/skin kanagawa
/skin kanagawa-wave
/skin tokyo-night-day
/skin everforest-light
/skin everforest-dark
/skin gruvbox-light
/skin gruvbox-dark
/skin flexoki-light
/skin flexoki-dark
/skin primer-light
/skin primer-dark
/skin catppuccin-latte
/skin catppuccin-frappe
/skin catppuccin-macchiato
/skin catppuccin-mocha
/skin noomz-rose-pine
/skin noomz-rose-pine-moon
/skin noomz-rose-pine-dawn
/skin noomz-rose-pine-dawn-contrast
```

To make it the default, set:

```sh
hermes config set display.skin modus-operandi
```

### kitty

Preferred custom theme location:

```sh
mkdir -p ~/.config/kitty/themes
cp themes/kitty/*.conf ~/.config/kitty/themes/
```

Then pick one with kitty's theme kitten:

```sh
kitty +kitten themes primer-dark
```

`gruvbox-dark` and `gruvbox-light` are omitted. kitty-themes already ships those names.

## Claude Code validation

Claude Code custom themes use the documented `name`, `base`, and `overrides` contract. Unknown override tokens are silently ignored by Claude Code, so this repo includes a validator to catch schema mistakes, invalid color syntax, and accidental undocumented tokens.

Validate the repo themes:

```sh
python3 scripts/validate-claude-theme.py themes/claude/*.json
```

Validate the active installed Claude Code copies:

```sh
python3 scripts/validate-claude-theme.py ~/.claude/themes/modus-operandi*.json
```

Validate all known active copies, including CCS-managed instances:

```sh
python3 scripts/validate-claude-theme.py \
  ~/.claude/themes/modus-operandi*.json \
  ~/.ccs/instances/work/themes/modus-operandi*.json \
  ~/.ccs/instances/personal/themes/modus-operandi*.json \
  themes/claude/*.json
```

For CI-like checks, fail on undocumented tokens too:

```sh
python3 scripts/validate-claude-theme.py --strict-tokens themes/claude/*.json
```

The active Claude Code preference should select the custom theme slug:

```sh
python3 - <<'PY'
import json, pathlib
print(json.loads(pathlib.Path('~/.claude/settings.json').expanduser().read_text()).get('theme'))
PY
```

Expected output:

```text
custom:modus-operandi
```

If CCS manages separate Claude instances, also confirm the intended theme slug in `~/.ccs/config.yaml` if that config is used by the instance.

### Runtime smoke testing

Claude Code reloads theme file edits from `~/.claude/themes/`. For disputed UI areas, temporarily set a known token to an obvious value, save the file, confirm the running Claude Code session changes, then revert it.

Useful token probes:

- collapsed hints: `inactive`, `subtle`
- picker/autocomplete/selection: `suggestion`
- input shell mode: `bashBorder`
- permission prompts: `permission`
- plan mode: `planMode`
- fullscreen message panels: `userMessageBackground`, `bashMessageBackgroundColor`, `messageActionsBackground`

Claude Code does not control the terminal application's canvas/background. These theme files can change message blocks, text colors, borders, selections, and related Claude UI tokens, but the full terminal page background comes from the terminal emulator profile (or from Claude internals not exposed as documented theme tokens). If the whole terminal background is too bright, adjust the terminal emulator profile instead, or use an ANSI-based Claude theme base such as `light-ansi` together with the terminal ANSI palette and background color.

Recommended terminal profile background colors:

| Theme | Terminal background |
| --- | --- |
| `modus-operandi` | `#fcf7ed` |
| `modus-operandi-tinted` | `#fbf7f0` |
| `kanagawa` | `#f2ecbc` |
| `kanagawa-wave` | `#1f1f28` |
| `tokyo-night-day` | `#e1e2e7` |
| `everforest-light` | `#fdf6e3` |
| `catppuccin-latte` | `#eff1f5` |
| `catppuccin-frappe` | `#303446` |
| `catppuccin-macchiato` | `#24273a` |
| `catppuccin-mocha` | `#1e1e2e` |
| `noomz-rose-pine` | `#191724` |
| `noomz-rose-pine-moon` | `#232136` |
| `noomz-rose-pine-dawn` | `#faf4ed` |
| `noomz-rose-pine-dawn-contrast` | `#faf4ed` |

If using cmux or another terminal wrapper, identify the host terminal profile before changing colors; do not kill production cmux processes just to force a reload.

## Files

```text
themes/
  claude/*.json
  pi.dev/*.json
  hermes/*.yaml
scripts/
  install.sh
  validate-claude-theme.py
  palette-report.py
  font-metrics.py
  font-report.py
  font-report-meta.json
docs/
  palette-report.html
  font-report.html
```

## Palette evaluation

`scripts/palette-report.py` measures every palette on WCAG 2.1 and APCA 0.1.9 (body text, dim text, worst accent, accent coverage, Oklab colour and accent separation, glare/halation headroom, and the lightness cost of repairing a failing accent). Both standards gate the accent terms — an accent counts toward coverage only if it clears 4.5:1 *and* APCA's Lc 60 content floor — then writes a self-contained report with per-mode leaderboards under two weightings (contrast-first and long-session), spider graphs, and a simulated terminal pane per palette (eight canonical ANSI roles drawn from the palette, plus a derived bright row):

```sh
python3 scripts/palette-report.py   # -> docs/palette-report.html
```

Open the HTML directly (`file://`); it has no external references. Hexes in the report are canonical upstream values, not the local ports, so the report stays valid when a port drifts.

## Typeface evaluation

`scripts/font-metrics.py` measures every monospaced font installed on the machine — outlines via fontTools, rasterisation via FreeType through Pillow — and writes `docs/font-metrics.json`. `scripts/font-report.py` turns that into `docs/font-report.html`:

```sh
python3 scripts/font-metrics.py        # -> docs/font-metrics.json (~3 min, ~580 faces)
python3 scripts/font-report.py         # -> docs/font-report.html
```

What is measured: x-height and cap-height from the outlines, cell advance and columns per screen, ink density of a screenful of text at 13&nbsp;px, stroke contrast from a rasterised `o`, the symmetric-difference distance of 34 confusable glyph pairs at design size and at 13&nbsp;px, the disambiguating cues on `0`, `1`, `l` and `I` (marked zero, flag, base, arm, foot, serifs), rule-glyph continuity across cell edges, icon and block coverage, weight ladder with the stem width of every installed weight, hinting and outline format.

The inventory walks the standard font directories and keeps a face when its printable ASCII
advances are all equal, rather than asking fontconfig for `spacing=100` — fontconfig reports
Monaco's spacing as dual, so a fontconfig-only inventory drops a font the terminal's picker
still offers. `docs/font-inventory.json` records what was scanned, kept and skipped, and the
report reconciles that against the list the terminal's font picker shows.

The report uses the evidence honestly: no study ranks typefaces by eye strain, so it ranks properties the literature does support (x-height and aperture, weight, spacing, cell geometry) and labels every axis with its evidence status. The polarity weight recommendation is marked as convention, because no weight × polarity trial exists.

The report also generates **ready-to-copy config** for the terminals installed here — kitty,
Ghostty, wezterm, Alacritty and iTerm2 — one block per font, with the point size, cell-width
and line-height adjustments derived from the measurements, and a copy button per block. Syntax
is checked against the installed versions, which matters: kitty 0.49 removed
`adjust_line_height` in favour of `modify_font cell_height`. Cover the top twelve fonts by
default; `--config-fonts 0` emits a block for every ranked font.

The specimen sections render with the palettes that won the palette report, read from `themes/claude/modus-operandi.json` and `themes/claude/catppuccin-mocha.json`. Specimens only display correctly where those fonts are installed; the metrics do not depend on that. `docs/font-metrics.json` is generated data — it is not tracked in git.

## License

MIT
