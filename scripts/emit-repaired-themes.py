#!/usr/bin/env python3
"""Apply report repair_cost() swaps to shipped themes; emit missing contender ports.

Reads canonical roles from palette-report.py. Does not write home configs.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pr', ROOT / 'scripts' / 'palette-report.py')
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

HEX = re.compile(r'#[0-9a-fA-F]{6}')
PI_SCHEMA = (
    'https://raw.githubusercontent.com/badlogic/pi-mono/main/'
    'packages/coding-agent/src/modes/interactive/theme/theme-schema.json'
)
HERMES_TAIL = '''
spinner:
  waiting_faces: ["(λ)", "(μ)", "(ν)", "(∴)"]
  thinking_faces: ["(λ)", "(∫)", "(∴)", "(∵)"]
  thinking_verbs:
    - reading
    - checking palette
    - composing
    - reasoning
    - applying colors
  wings:
    - ["⟪", "⟫"]
    - ["‹", "›"]

branding:
  agent_name: "Hermes Agent"
  welcome: "Welcome to Hermes Agent! Type your message or /help for commands."
  goodbye: "Goodbye! ⚕"
  response_label: " ⚕ Hermes "
  prompt_symbol: "❯"
  help_header: "[?] Available Commands"

tool_prefix: "│"
'''

# Report palette -> shipped slug. Soft/modus skipped.
SHIPPED = {
    'flexoki-light': 'flexoki-light',
    'flexoki-dark': 'flexoki-dark',
    'gruvbox-light': 'gruvbox-light',
    'catppuccin-latte': 'catppuccin-latte',
    'everforest-light-med': 'everforest-light',
    'everforest-dark-med': 'everforest-dark',
    'gruvbox-dark': 'gruvbox-dark',
}

EXISTING = (
    'catppuccin-latte',
    'everforest-light',
    'gruvbox-dark',
)


def swaps_for(key: str) -> dict[str, str]:
    p = pr.PALETTES[key]
    out = {}
    for _name, (hx, _kind) in p['roles'].items():
        if pr.wcag(hx, p['bg']) < 4.5:
            cand, _d = pr.repair_cost(hx, p['bg'])
            out[hx.lower()] = cand.lower()
    return out


def apply_swaps(path: Path, mapping: dict[str, str]) -> int:
    text = path.read_text()
    n = 0

    def repl(m):
        nonlocal n
        h = m.group(0).lower()
        if h in mapping:
            n += 1
            return mapping[h]
        return m.group(0)

    new = HEX.sub(repl, text)
    if new != text:
        path.write_text(new)
    return n


def dump_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2) + '\n')


def hermes(path: Path, name: str, desc: str, colors: dict[str, str]) -> None:
    lines = [f'name: {name}', f'description: {desc}', '', 'colors:']
    for k, v in colors.items():
        lines.append(f'  {k}: "{v}"')
    lines.append(HERMES_TAIL)
    path.write_text('\n'.join(lines))


def pi_theme(name: str, vars_: dict, colors: dict, export: dict) -> dict:
    return {'$schema': PI_SCHEMA, 'name': name, 'vars': vars_,
            'colors': colors, 'export': export}


PI_COLORS = {
    'accent': 'accent',
    'border': 'border',
    'borderAccent': 'accent',
    'borderMuted': 'dim',
    'success': 'green',
    'error': 'red',
    'warning': 'yellow',
    'muted': 'muted',
    'dim': 'dim',
    'text': 'text',
    'thinkingText': 'muted',
    'selectedBg': 'selection',
    'userMessageBg': 'raised',
    'userMessageText': 'text',
    'customMessageBg': 'infoBg',
    'customMessageText': 'text',
    'customMessageLabel': 'purple',
    'toolPendingBg': 'infoBg',
    'toolSuccessBg': 'addedBgDim',
    'toolErrorBg': 'removedBgDim',
    'toolTitle': 'blue',
    'toolOutput': 'text',
    'mdHeading': 'yellow',
    'mdLink': 'blue',
    'mdLinkUrl': 'muted',
    'mdCode': 'cyan',
    'mdCodeBlock': 'text',
    'mdCodeBlockBorder': 'border',
    'mdQuote': 'muted',
    'mdQuoteBorder': 'border',
    'mdHr': 'border',
    'mdListBullet': 'cyan',
    'toolDiffAdded': 'green',
    'toolDiffRemoved': 'red',
    'toolDiffContext': 'muted',
    'syntaxComment': 'dim',
    'syntaxKeyword': 'red',
    'syntaxFunction': 'green',
    'syntaxVariable': 'text',
    'syntaxString': 'green',
    'syntaxNumber': 'purple',
    'syntaxType': 'yellow',
    'syntaxOperator': 'orange',
    'syntaxPunctuation': 'dim',
    'thinkingOff': 'dim',
    'thinkingMinimal': 'muted',
    'thinkingLow': 'cyan',
    'thinkingMedium': 'blue',
    'thinkingHigh': 'purple',
    'thinkingXhigh': 'red',
    'bashMode': 'orange',
}


def claude(name, base, c):
    pink = c.get('pink', c['purple'])
    indigo = c.get('indigo', c['blue'])
    return {
        'name': name,
        'base': base,
        'overrides': {
            'autoAccept': c['green'],
            'bashBorder': c['orange'],
            'claude': c['purple'],
            'claudeShimmer': c.get('purple2', c['purple']),
            'permission': c['orange'],
            'permissionShimmer': c.get('orange2', c['yellow']),
            'planMode': c['cyan'],
            'ide': c['blue'],
            'promptBorder': c['blue'],
            'promptBorderShimmer': indigo,
            'text': c['text'],
            'inverseText': c['bg'],
            'inactive': c['dim'],
            'inactiveShimmer': c.get('muted', c['dim']),
            'subtle': c.get('muted', c['dim']),
            'suggestion': c['blue'],
            'remember': c['purple'],
            'success': c['green'],
            'error': c['red'],
            'warning': c['yellow'],
            'merged': c['purple'],
            'warningShimmer': c['orange'],
            'diffAdded': c['green'],
            'diffRemoved': c['red'],
            'diffAddedDimmed': c.get('added_dim', c['green']),
            'diffRemovedDimmed': c.get('removed_dim', c['red']),
            'diffAddedWord': c['green'],
            'diffRemovedWord': c['red'],
            'red_FOR_SUBAGENTS_ONLY': c['red'],
            'blue_FOR_SUBAGENTS_ONLY': c['blue'],
            'green_FOR_SUBAGENTS_ONLY': c['green'],
            'yellow_FOR_SUBAGENTS_ONLY': c['yellow'],
            'purple_FOR_SUBAGENTS_ONLY': c['purple'],
            'orange_FOR_SUBAGENTS_ONLY': c['orange'],
            'pink_FOR_SUBAGENTS_ONLY': pink,
            'cyan_FOR_SUBAGENTS_ONLY': c['cyan'],
            'rainbow_red': c['red'],
            'rainbow_orange': c['orange'],
            'rainbow_yellow': c['yellow'],
            'rainbow_green': c['green'],
            'rainbow_blue': c['blue'],
            'rainbow_indigo': indigo,
            'rainbow_violet': c['purple'],
            'rainbow_red_shimmer': c.get('red2', c['red']),
            'rainbow_orange_shimmer': c.get('orange2', c['orange']),
            'rainbow_yellow_shimmer': c.get('yellow2', c['yellow']),
            'rainbow_green_shimmer': c.get('green2', c['cyan']),
            'rainbow_blue_shimmer': indigo,
            'rainbow_indigo_shimmer': indigo,
            'rainbow_violet_shimmer': c.get('purple2', pink),
            'userMessageBackground': c['raised'],
            'userMessageBackgroundHover': c['hover'],
            'selectionBg': c['selection'],
            'bashMessageBackgroundColor': c['info'],
            'memoryBackgroundColor': c['raised'],
            'rate_limit_fill': c['cyan'],
            'rate_limit_empty': c.get('border', c['dim']),
            'fastMode': c['orange'],
            'fastModeShimmer': c.get('orange2', c['yellow']),
            'briefLabelYou': c['purple'],
            'briefLabelClaude': c['blue'],
            'messageActionsBackground': c['hover'],
        },
    }


def repaired(key, name):
    p = pr.PALETTES[key]
    roles = {}
    for n, (hx, kind) in p['roles'].items():
        if pr.wcag(hx, p['bg']) < 4.5:
            cand, _ = pr.repair_cost(hx, p['bg'])
            roles[n] = cand.lower()
        else:
            roles[n] = hx.lower()
    return roles


def hermes_colors(c):
    return {
        'banner_border': c['dim'],
        'banner_title': c['text'],
        'banner_accent': c.get('pink', c['purple']),
        'banner_dim': c['dim'],
        'banner_text': c['text'],
        'ui_accent': c['blue'],
        'ui_label': c['cyan'],
        'ui_ok': c['green'],
        'ui_error': c['red'],
        'ui_warn': c['yellow'],
        'prompt': c['text'],
        'input_rule': c['border'],
        'response_border': c['purple'],
        'session_label': c['blue'],
        'session_border': c['border'],
        'status_bar_bg': c['raised'],
        'status_bar_text': c['text'],
        'status_bar_strong': c['purple'],
        'status_bar_dim': c['dim'],
        'status_bar_good': c.get('green2', c['green']),
        'status_bar_warn': c.get('yellow2', c['yellow']),
        'status_bar_bad': c['orange'],
        'status_bar_critical': c.get('red2', c['red']),
        'voice_status_bg': c['raised'],
        'selection_bg': c['selection'],
        'completion_menu_bg': c['info'],
        'completion_menu_current_bg': c['selection'],
        'completion_menu_meta_bg': c['raised'],
        'completion_menu_meta_current_bg': c['hover'],
    }


def pi_from(c, accent='orange'):
    colors = dict(PI_COLORS)
    colors['accent'] = accent
    colors['borderAccent'] = accent
    colors['customMessageLabel'] = 'purple'
    vars_ = {
        'base': c['bg'],
        'text': c['text'],
        'muted': c.get('muted', c['dim']),
        'dim': c['dim'],
        'raised': c['raised'],
        'border': c['border'],
        'selection': c['selection'],
        'infoBg': c['info'],
        'addedBgDim': c.get('added_bg', c['raised']),
        'removedBgDim': c.get('removed_bg', c['hover']),
        'red': c['red'],
        'orange': c['orange'],
        'yellow': c['yellow'],
        'green': c['green'],
        'cyan': c['cyan'],
        'blue': c['blue'],
        'purple': c['purple'],
        'accent': c[accent],
    }
    if c.get('pink'):
        vars_['magenta'] = c['pink']
    for src, dest in (('red2', 'redBright'), ('green2', 'greenBright'),
                      ('yellow2', 'yellowBright'), ('indigo', 'blueBright')):
        if c.get(src):
            vars_[dest] = c[src]
    return pi_theme(c['slug'], vars_, colors,
                    {'pageBg': 'base', 'cardBg': 'raised', 'infoBg': 'infoBg'})


def emit_new(c):
    slug = c['slug']
    dump_json(ROOT / 'themes' / 'claude' / f'{slug}.json',
              claude(c['title'], c['base'], c))
    dump_json(ROOT / 'themes' / 'pi.dev' / f'{slug}.json',
              pi_from(c, c.get('accent_var', 'orange')))
    hermes(ROOT / 'themes' / 'hermes' / f'{slug}.yaml', slug, c['desc'],
           hermes_colors(c))
    print(f'wrote {slug} x3')


def main():
    # Existing ports: swap failing role hexes in place.
    for report_key, slug in SHIPPED.items():
        if slug not in EXISTING:
            continue
        mapping = swaps_for(report_key)
        if not mapping:
            print(f'{slug}: no swaps')
            continue
        for cli, ext in (('claude', '.json'), ('pi.dev', '.json'), ('hermes', '.yaml')):
            path = ROOT / 'themes' / cli / f'{slug}{ext}'
            n = apply_swaps(path, mapping)
            print(f'swap {cli}/{slug}{ext}: {n} hexes  {mapping}')

    fl = repaired('flexoki-light', 'flexoki-light')
    emit_new(dict(
        slug='flexoki-light', title='Flexoki Light', base='light',
        desc='Flexoki light with yellow/green/cyan lifted to WCAG AA on paper',
        bg='#fffcf0', text=fl['tx'], dim=fl['tx-2'], muted=fl['tx-2'],
        raised='#f2f0e5', hover='#e6e4d9', selection='#dad8ce',
        info='#e6e4d9', border='#cecdc3',
        red=fl['red'], orange=fl['orange'], yellow=fl['yellow'],
        green=fl['green'], cyan=fl['cyan'], blue=fl['blue'],
        purple=fl['purple'], pink=fl['magenta'],
        added_dim='#e6e4d9', removed_dim='#e6e4d9',
        added_bg='#e6e4d9', removed_bg='#e6e4d9',
        accent_var='orange',
    ))

    fd = repaired('flexoki-dark', 'flexoki-dark')
    emit_new(dict(
        slug='flexoki-dark', title='Flexoki Dark', base='dark',
        desc='Flexoki dark with red/blue lifted to WCAG AA on base-950',
        bg='#1c1b1a', text=fd['base-200'], dim=fd['base-500'], muted=fd['base-500'],
        raised='#282726', hover='#343331', selection='#403e3c',
        info='#282726', border='#575653',
        red=fd['red'], orange=fd['orange'], yellow=fd['yellow'],
        green=fd['green'], cyan=fd['cyan'], blue=fd['blue'],
        purple=fd['purple'], pink=fd['magenta'],
        added_dim='#282726', removed_dim='#343331',
        added_bg='#282726', removed_bg='#343331',
        accent_var='orange',
    ))

    gl = repaired('gruvbox-light', 'gruvbox-light')
    emit_new(dict(
        slug='gruvbox-light', title='Gruvbox Light', base='light',
        desc='Gruvbox light with gray/green/yellow/aqua lifted to WCAG AA on bg0',
        bg='#fbf1c7', text=gl['fg'], dim=gl['gray'], muted=gl['gray'],
        raised='#f2e5bc', hover='#ebdbb2', selection='#d5c4a1',
        info='#ebdbb2', border='#bdae93',
        red=gl['red'], orange=gl['orange'], yellow=gl['yellow'],
        green=gl['green'], cyan=gl['aqua'], blue=gl['blue'],
        purple=gl['purple'],
        added_dim='#ebdbb2', removed_dim='#ebdbb2',
        added_bg='#ebdbb2', removed_bg='#f2e5bc',
        accent_var='orange',
    ))

    ed = repaired('everforest-dark-med', 'everforest-dark')
    emit_new(dict(
        slug='everforest-dark', title='Everforest Dark', base='dark',
        desc='Everforest Dark Medium with grey1 lifted to WCAG AA on bg0',
        bg='#2d353b', text=ed['fg'], dim=ed['grey1'], muted='#9da9a0',
        raised='#343f44', hover='#3d484d', selection='#543a48',
        info='#3a515d', border='#4f585e',
        red=ed['red'], orange=ed['orange'], yellow=ed['yellow'],
        green=ed['green'], cyan=ed['aqua'], blue=ed['blue'],
        purple=ed['purple'],
        added_dim='#425047', removed_dim='#514045',
        added_bg='#425047', removed_bg='#514045',
        accent_var='green',
    ))

    pl = repaired('primer-light', 'primer-light')
    emit_new(dict(
        slug='primer-light', title='Primer Light', base='light',
        desc='GitHub Primer light ANSI with blueBright and magentaBright lifted to WCAG AA on canvas',
        bg='#ffffff', text=pl['black'], dim=pl['white'], muted=pl['white'],
        raised='#f6f8fa', hover='#eaeef2', selection='#ddf4ff',
        info='#ddf4ff', border='#d0d7de',
        red=pl['red'], red2=pl['redBright'],
        orange=pl['yellowBright'], yellow=pl['yellow'], yellow2=pl['yellowBright'],
        green=pl['green'], green2=pl['greenBright'],
        cyan=pl['blueBright'], blue=pl['blue'], indigo=pl['blueBright'],
        purple=pl['magenta'], purple2=pl['magentaBright'], pink=pl['magentaBright'],
        added_bg='#dafbe1', removed_bg='#ffebe9',
        added_dim='#dafbe1', removed_dim='#ffebe9',
        accent_var='blue',
    ))

    pd = repaired('primer-dark', 'primer-dark')
    emit_new(dict(
        slug='primer-dark', title='Primer Dark', base='dark',
        desc='GitHub Primer dark ANSI with gray lifted to WCAG AA on canvas',
        bg='#0d1117', text=pd['white'], dim=pd['gray'], muted=pd['gray'],
        raised='#161b22', hover='#21262d', selection='#21262d',
        info='#161b22', border='#30363d',
        red=pd['red'], red2=pd['redBright'],
        orange=pd['yellowBright'], yellow=pd['yellow'], yellow2=pd['yellowBright'],
        green=pd['green'], green2=pd['greenBright'],
        cyan=pd['blueBright'], blue=pd['blue'], indigo=pd['blueBright'],
        purple=pd['magenta'], purple2=pd['magentaBright'], pink=pd['magentaBright'],
        added_bg='#161b22', removed_bg='#21262d',
        added_dim='#161b22', removed_dim='#21262d',
        accent_var='blue',
    ))


if __name__ == '__main__':
    main()
