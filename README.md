# noomz-themes

High-contrast themes for agent CLIs.

Currently included for Claude Code, pi.dev, and Hermes Agent:

- `modus-operandi`
- `modus-operandi-tinted` (uses canonical `modus-operandi-tinted` palette values from https://protesilaos.com/emacs/modus-themes-colors)
- `kanagawa` (Kanagawa Lotus-inspired light adaptation)
- `kanagawa-wave` (Kanagawa Wave-inspired dark adaptation)
- `tokyo-night-day` (TokyoNight Day-inspired adaptation)
- `everforest-light` (Everforest Light Medium-inspired adaptation)
- `catppuccin-latte` (Catppuccin Latte light palette)
- `catppuccin-frappe` (Catppuccin Frappé dark palette)
- `catppuccin-macchiato` (Catppuccin Macchiato dark palette)
- `catppuccin-mocha` (Catppuccin Mocha dark palette)
- `noomz-rose-pine` (Rosé Pine main dark palette)
- `noomz-rose-pine-moon` (Rosé Pine Moon dark palette)
- `noomz-rose-pine-dawn` (Rosé Pine Dawn light palette)
- `noomz-rose-pine-dawn-contrast` (higher-contrast Rosé Pine Dawn adaptation)

The palettes keep readability high while darkening low-contrast text where needed, especially collapsed-output hints, file/link paths, dim metadata, neutral borders, and selection surfaces.

The Catppuccin themes keep the upstream accents. Dim and comment text uses the first of Overlay 2, Subtext 0, or Subtext 1 that reaches 4.5:1 on the base color, which is Overlay 2 in the dark flavors and Subtext 1 in Latte.

Palette sources:

- Modus: https://protesilaos.com/emacs/modus-themes-colors
- Kanagawa/Kawakawa adaptation: https://github.com/rebelot/kanagawa.nvim
- Tokyo Night Day: https://github.com/folke/tokyonight.nvim
- Everforest Light Medium: https://github.com/sainnhe/everforest/blob/master/palette.md
- Catppuccin: https://github.com/catppuccin/palette
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

Then set `theme` to one theme slug in `~/.pi/agent/settings.json`, for example `modus-operandi`, `kanagawa`, `kanagawa-wave`, `tokyo-night-day`, `everforest-light`, `catppuccin-latte`, `catppuccin-frappe`, `catppuccin-macchiato`, `catppuccin-mocha`, `noomz-rose-pine`, `noomz-rose-pine-moon`, `noomz-rose-pine-dawn`, or `noomz-rose-pine-dawn-contrast`.

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
```

## License

MIT
