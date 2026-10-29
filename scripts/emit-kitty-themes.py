#!/usr/bin/env python3
"""Emit themes/kitty/<slug>.conf from pi.dev vars. Skip names kitty-themes already has."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KITTY_THEMES = Path.home() / '.config/kitty/kitty-themes/themes'
OUT = ROOT / 'themes' / 'kitty'

spec = importlib.util.spec_from_file_location('pr', ROOT / 'scripts' / 'palette-report.py')
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def pick(v, *keys):
    for k in keys:
        if k in v and isinstance(v[k], str) and v[k].startswith('#'):
            return v[k].lower()
    return None


def existing_kitty_stems():
    if not KITTY_THEMES.is_dir():
        return set()
    return {p.stem.lower().replace('_', '-') for p in KITTY_THEMES.glob('*.conf')}


def ansi(v):
    bg = pick(v, 'base', 'bg', 'bg0')
    fg = pick(v, 'text', 'fg')
    dim = pick(v, 'dim', 'grey1', 'dimGray', 'muted', 'comment', 'fgDim', 'subtle')
    muted = pick(v, 'muted', 'mutedGray', 'grey0', 'faintGray', 'nontext') or dim
    raised = pick(v, 'raised', 'surface', 'overlay', 'bg1', 'soft') or bg
    border = pick(v, 'border', 'borderGray', 'grey2') or dim
    sel = pick(v, 'selection', 'bgVisual', 'highlightMed', 'pmenuSel') or raised
    red = pick(v, 'red', 'love', 'diagError', 'preproc', 'vcsRemoved')
    green = pick(v, 'green', 'pine', 'leaf', 'string', 'vcsAdded', 'diagOk')
    yellow = pick(v, 'yellow', 'gold', 'type', 'vcsChanged', 'diagWarning')
    blue = pick(v, 'blue', 'function', 'pine')
    magenta = pick(v, 'mauve', 'purple', 'iris', 'magenta', 'statement', 'parameter')
    cyan = pick(v, 'teal', 'cyan', 'aqua', 'foam', 'sky', 'punct', 'diagHint')
    orange = pick(v, 'orange', 'peach', 'constant', 'gold') or yellow
    red_b = pick(v, 'redBright', 'orange', 'peach', 'rose') or red
    green_b = pick(v, 'greenBright', 'statusline1') or green
    yellow_b = pick(v, 'yellowBright') or orange or yellow
    blue_b = pick(v, 'blueBright', 'blue2', 'special1') or blue
    mag_b = pick(v, 'magentaBright', 'pink', 'rose') or magenta
    cyan_b = pick(v, 'sky', 'cyan2') or cyan
    missing = [n for n, x in (
        ('bg', bg), ('fg', fg), ('red', red), ('green', green),
        ('yellow', yellow), ('blue', blue), ('magenta', magenta), ('cyan', cyan),
    ) if not x]
    if missing:
        raise SystemExit(f'missing roles {missing} in {sorted(v)}')
    dark = pr.rel_lum(pr.hex2rgb(bg)) < 0.5
    c0 = raised if dark else (dim or fg)
    c7 = muted or dim or fg
    c8 = dim or border or muted
    c15 = fg if dark else bg
    cursor = orange or blue or fg
    return dict(
        background=bg, foreground=fg, cursor=cursor,
        selection_background=sel or raised, selection_foreground=fg,
        url_color=blue,
        color0=c0, color1=red, color2=green, color3=yellow,
        color4=blue, color5=magenta, color6=cyan, color7=c7,
        color8=c8, color9=red_b, color10=green_b, color11=yellow_b,
        color12=blue_b, color13=mag_b, color14=cyan_b, color15=c15,
        active_tab_foreground=bg, active_tab_background=cursor,
        inactive_tab_foreground=fg, inactive_tab_background=raised,
    )


def render(slug, colors):
    lines = [
        f'## name: {slug}',
        '## author: noomz-themes',
        '',
    ]
    order = [
        'background', 'foreground', 'cursor',
        'selection_foreground', 'selection_background', 'url_color',
        'color0', 'color1', 'color2', 'color3', 'color4', 'color5', 'color6', 'color7',
        'color8', 'color9', 'color10', 'color11', 'color12', 'color13', 'color14', 'color15',
        'active_tab_foreground', 'active_tab_background',
        'inactive_tab_foreground', 'inactive_tab_background',
    ]
    for k in order:
        lines.append(f'{k:<28} {colors[k]}')
    lines.append('')
    return '\n'.join(lines)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    skip = existing_kitty_stems()
    wrote = skipped = 0
    for path in sorted((ROOT / 'themes' / 'pi.dev').glob('*.json')):
        slug = path.stem
        if slug.lower() in skip:
            print(f'skip (kitty-themes has) {slug}')
            skipped += 1
            continue
        vars_ = json.loads(path.read_text())['vars']
        (OUT / f'{slug}.conf').write_text(render(slug, ansi(vars_)))
        wrote += 1
        print(f'wrote {slug}')
    print(f'done wrote={wrote} skipped={skipped}')


if __name__ == '__main__':
    main()
