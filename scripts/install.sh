#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CLAUDE_THEMES_DIR="$ROOT/themes/claude"
PI_THEMES_DIR="$ROOT/themes/pi.dev"
HERMES_SKINS_DIR="$ROOT/themes/hermes"
VALIDATOR="$ROOT/scripts/validate-claude-theme.py"
CCS_INSTANCES_DIR="$HOME/.ccs/instances"

copy_claude_themes() {
  dest="$1"
  mkdir -p "$dest"
  for theme in "$CLAUDE_THEMES_DIR"/*.json; do
    cp "$theme" "$dest/$(basename "$theme")"
  done
}

if [ "${STRICT:-0}" = "1" ]; then
  python3 "$VALIDATOR" --strict-tokens "$CLAUDE_THEMES_DIR"/*.json
else
  python3 "$VALIDATOR" "$CLAUDE_THEMES_DIR"/*.json
fi

copy_claude_themes "$HOME/.claude/themes"

ccs_count=0
if [ -d "$CCS_INSTANCES_DIR" ]; then
  for instance in "$CCS_INSTANCES_DIR"/*; do
    [ -d "$instance" ] || continue
    copy_claude_themes "$instance/themes"
    ccs_count=$((ccs_count + 1))
  done
fi

mkdir -p "$HOME/.pi/agent/themes"
for theme in "$PI_THEMES_DIR"/*.json; do
  cp "$theme" "$HOME/.pi/agent/themes/$(basename "$theme")"
done

mkdir -p "$HOME/.hermes/skins"
for skin in "$HERMES_SKINS_DIR"/*.yaml; do
  cp "$skin" "$HOME/.hermes/skins/$(basename "$skin")"
done

KITTY_THEMES_DIR="$ROOT/themes/kitty"
mkdir -p "$HOME/.config/kitty/themes"
if [ -d "$KITTY_THEMES_DIR" ]; then
  for theme in "$KITTY_THEMES_DIR"/*.conf; do
    [ -e "$theme" ] || continue
    cp "$theme" "$HOME/.config/kitty/themes/$(basename "$theme")"
  done
fi

printf '%s\n' "Installed noomz themes for Claude Code, pi.dev, Hermes Agent, and kitty."
if [ "$ccs_count" -gt 0 ]; then
  printf '%s\n' "CCS profiles updated: $ccs_count."
fi
printf '%s\n' "Claude variants: modus-operandi, modus-operandi-tinted, kanagawa, tokyo-night-day, everforest-light, everforest-dark, gruvbox-light, gruvbox-dark, flexoki-light, flexoki-dark, primer-light, primer-dark, catppuccin-latte, catppuccin-frappe, catppuccin-macchiato, catppuccin-mocha, noomz-rose-pine, noomz-rose-pine-moon, noomz-rose-pine-dawn, noomz-rose-pine-dawn-contrast. Activate with /theme <variant>."
printf '%s\n' "Hermes variants: modus-operandi, modus-operandi-tinted, kanagawa, tokyo-night-day, everforest-light, everforest-dark, gruvbox-light, gruvbox-dark, flexoki-light, flexoki-dark, primer-light, primer-dark, catppuccin-latte, catppuccin-frappe, catppuccin-macchiato, catppuccin-mocha, noomz-rose-pine, noomz-rose-pine-moon, noomz-rose-pine-dawn, noomz-rose-pine-dawn-contrast. Activate with /skin <variant>."
printf '%s\n' "pi.dev variants: set theme to modus-operandi, modus-operandi-tinted, kanagawa, tokyo-night-day, everforest-light, everforest-dark, gruvbox-light, gruvbox-dark, flexoki-light, flexoki-dark, primer-light, primer-dark, catppuccin-latte, catppuccin-frappe, catppuccin-macchiato, catppuccin-mocha, noomz-rose-pine, noomz-rose-pine-moon, noomz-rose-pine-dawn, or noomz-rose-pine-dawn-contrast in ~/.pi/agent/settings.json."
