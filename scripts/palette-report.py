#!/usr/bin/env python3
"""Generate a self-contained palette evaluation report (HTML + SVG radar charts).

Every number is computed here from canonical upstream hexes: WCAG 2.1 relative
luminance and APCA 0.1.9 (W3C silver draft constants). No network, no deps.

Usage:
  python3 scripts/palette-report.py                 # -> docs/palette-report.html
  python3 scripts/palette-report.py --out /tmp/r.html
  python3 scripts/palette-report.py --text          # leaderboard to stdout only
"""
import argparse
import colorsys
import math
import pathlib
from html import escape

# --------------------------------------------------------------------- colour
def hex2rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def srgb_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(rgb):
    r, g, b = (srgb_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag(fg, bg):
    a, b = rel_lum(hex2rgb(fg)), rel_lum(hex2rgb(bg))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# APCA 0.1.9 (silver draft). 0.2.x uses different exponents - state the version.
RCO, GCO, BCO = 0.2126729, 0.7151522, 0.0721750
NORM_BG, NORM_TXT, REV_TXT, REV_BG = 0.56, 0.57, 0.62, 0.65
BLK_THRS, BLK_CLMP, SCALE, LO_CLIP = 0.022, 1.414, 1.14, 0.1
LO_BOW_OFF, LO_WOB_OFF, DELTA_Y_MIN = 0.027, 0.027, 0.0005


def apca_y(rgb):
    r, g, b = (c / 255.0 for c in rgb)
    return RCO * r ** 2.4 + GCO * g ** 2.4 + BCO * b ** 2.4


def apca(fg, bg):
    ty, by = apca_y(hex2rgb(fg)), apca_y(hex2rgb(bg))
    ty = ty if ty > BLK_THRS else ty + (BLK_THRS - ty) ** BLK_CLMP
    by = by if by > BLK_THRS else by + (BLK_THRS - by) ** BLK_CLMP
    if abs(by - ty) < DELTA_Y_MIN:
        return 0.0
    if by > ty:
        s = (by ** NORM_BG - ty ** NORM_TXT) * SCALE
        return 0.0 if s < LO_CLIP else (s - LO_BOW_OFF) * 100
    s = (by ** REV_BG - ty ** REV_TXT) * SCALE
    return 0.0 if s > -LO_CLIP else (s + LO_WOB_OFF) * 100


def repair_cost(hexv, bg, target=4.5):
    """Hold hue+saturation, move lightness toward the far pole until target."""
    import colorsys
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in hex2rgb(hexv)))
    direction = -1 if rel_lum(hex2rgb(bg)) > 0.18 else 1
    cur = l
    while 0 < cur < 1:
        cur += direction * 0.004
        cand = '#%02x%02x%02x' % tuple(
            round(c * 255) for c in colorsys.hls_to_rgb(h, cur, s))
        if wcag(cand, bg) >= target:
            return cand, abs(cur - l)
    return None, None


# ------------------------------------------------------------------- palettes
# role: (hex, kind)   kind in {body, dim, accent}
PALETTES = {
    'modus-operandi': dict(
        mode='light', bg='#fcf7ed', colour='#0031a9', contender=True,
        source='protesilaos.com/emacs/modus-themes-colors',
        intent='Accessibility-first; targets WCAG AAA. Documented method, not a claim. '
               'Accents are the Modus v4 values; the canvas is #fcf7ed, the port\'s '
               'terminal background, not upstream bg-main #ffffff (measured on white, '
               'body text would be 21:1 and glare headroom zero). Note: the shipped '
               'Claude port is a re-tuned variant — 60 of 61 tokens moved in a comfort '
               'pass, because Claude draws text on tinted panels — so installed contrast '
               'differs from these upstream hexes (body 18.32, inactive 9.71, worst '
               'accent 7.02).',
        roles={'fg-main': ('#000000', 'body'), 'fg-dim': ('#595959', 'dim'),
               'red': ('#a60000', 'accent'), 'green': ('#006800', 'accent'),
               'yellow': ('#6f5500', 'accent'), 'blue': ('#0031a9', 'accent'),
               'magenta': ('#721045', 'accent'), 'cyan': ('#005e8b', 'accent')}),
    'flexoki-light': dict(
        mode='light', bg='#fffcf0', colour='#af3029', contender=True,
        source='stephango.com/flexoki (canonical README hexes)',
        intent='Oklab-derived ramps, exponentially increased chroma, "ink on paper" brief.',
        roles={'tx': ('#100f0f', 'body'), 'tx-2': ('#6f6e69', 'dim'),
               'red': ('#af3029', 'accent'), 'orange': ('#bc5215', 'accent'),
               'yellow': ('#ad8301', 'accent'), 'green': ('#66800b', 'accent'),
               'cyan': ('#24837b', 'accent'), 'blue': ('#205ea6', 'accent'),
               'purple': ('#5e409d', 'accent'), 'magenta': ('#a02f6f', 'accent')}),
    'gruvbox-light': dict(
        mode='light', bg='#fbf1c7', colour='#79740e', contender=True,
        source='morhetz/gruvbox xresources',
        intent='Designer intent only: "contrast enough and still pleasant for the eyes".',
        roles={'fg': ('#3c3836', 'body'), 'gray': ('#7c6f64', 'dim'),
               'red': ('#9d0006', 'accent'), 'green': ('#79740e', 'accent'),
               'yellow': ('#b57614', 'accent'), 'blue': ('#076678', 'accent'),
               'purple': ('#8f3f71', 'accent'), 'aqua': ('#427b58', 'accent'),
               'orange': ('#af3a03', 'accent')}),

    'catppuccin-latte': dict(
        mode='light', bg='#eff1f5', colour='#8839ef', contender=True,
        source='catppuccin/palette',
        intent='"Middle ground between low and high contrast" - pastel by design.',
        roles={'text': ('#4c4f69', 'body'), 'subtext0': ('#6c6f85', 'dim'),
               'red': ('#d20f39', 'accent'), 'green': ('#40a02b', 'accent'),
               'yellow': ('#df8e1d', 'accent'), 'blue': ('#1e66f5', 'accent'),
               'mauve': ('#8839ef', 'accent'), 'teal': ('#179299', 'accent'),
               'peach': ('#fe640b', 'accent'), 'pink': ('#ea76cb', 'accent')}),
    'everforest-light-med': dict(
        mode='light', bg='#fdf6e3', colour='#8da101', contender=True,
        source='sainnhe/everforest palette.md',
        intent='Intent only: "warm and soft ... to protect developers\' eyes".',
        roles={'fg': ('#5c6a72', 'body'), 'grey1': ('#939f91', 'dim'),
               'red': ('#f85552', 'accent'), 'orange': ('#f57d26', 'accent'),
               'yellow': ('#dfa000', 'accent'), 'green': ('#8da101', 'accent'),
               'aqua': ('#35a77c', 'accent'), 'blue': ('#3a94c5', 'accent'),
               'purple': ('#df69ba', 'accent')}),
    'everforest-light-soft': dict(
        mode='light', bg='#e5dfc5', colour='#df69ba', contender=True,
        source='sainnhe/everforest palette.md (soft)',
        intent='Soft-contrast variant: the same accents on a dimmer page.',
        roles={'fg': ('#5c6a72', 'body'), 'grey1': ('#939f91', 'dim'),
               'red': ('#f85552', 'accent'), 'orange': ('#f57d26', 'accent'),
               'yellow': ('#dfa000', 'accent'), 'green': ('#8da101', 'accent'),
               'aqua': ('#35a77c', 'accent'), 'blue': ('#3a94c5', 'accent'),
               'purple': ('#df69ba', 'accent')}),
    'primer-light': dict(
        mode='light', bg='#ffffff', colour='#0969da', contender=False,
        source='primer/primitives syntax.json5 ansi block',
        intent='Audited UI system. ANSI roles, not a syntax theme - reference only.',
        roles={'black': ('#1f2328', 'body'), 'white': ('#59636e', 'dim'),
               'red': ('#cf222e', 'accent'), 'redBright': ('#a40e26', 'accent'),
               'green': ('#116329', 'accent'), 'greenBright': ('#1a7f37', 'accent'),
               'yellow': ('#4d2d00', 'accent'), 'yellowBright': ('#633c01', 'accent'),
               'blue': ('#0969da', 'accent'), 'blueBright': ('#218bff', 'accent'),
               'magenta': ('#8250df', 'accent'),
               'magentaBright': ('#a475f9', 'accent')}),

    'catppuccin-mocha': dict(
        mode='dark', bg='#1e1e2e', colour='#cba6f7', contender=True,
        source='catppuccin/palette',
        intent='Pastel accents; v0.1.3 claims WCAG AAA for accents on base.',
        roles={'text': ('#cdd6f4', 'body'), 'subtext0': ('#a6adc8', 'dim'),
               'red': ('#f38ba8', 'accent'), 'green': ('#a6e3a1', 'accent'),
               'yellow': ('#f9e2af', 'accent'), 'blue': ('#89b4fa', 'accent'),
               'mauve': ('#cba6f7', 'accent'), 'teal': ('#94e2d5', 'accent'),
               'peach': ('#fab387', 'accent'), 'pink': ('#f5c2e7', 'accent')}),
    'flexoki-dark': dict(
        mode='dark', bg='#1c1b1a', colour='#d14d41', contender=True,
        source='stephango.com/flexoki (base-950 pairing)',
        intent='400-ramp accents on base-950; paper reserved for headings.',
        roles={'base-200': ('#cecdc3', 'body'), 'base-500': ('#878580', 'dim'),
               'red': ('#d14d41', 'accent'), 'orange': ('#da702c', 'accent'),
               'yellow': ('#d0a215', 'accent'), 'green': ('#879a39', 'accent'),
               'cyan': ('#3aa99f', 'accent'), 'blue': ('#4385be', 'accent'),
               'purple': ('#8b7ec8', 'accent'), 'magenta': ('#ce5d97', 'accent')}),
    'gruvbox-dark': dict(
        mode='dark', bg='#282828', colour='#fabd2f', contender=True,
        source='morhetz/gruvbox xresources',
        intent='Medium-contrast background by default; hard/soft available.',
        roles={'fg': ('#ebdbb2', 'body'), 'gray': ('#928374', 'dim'),
               'red': ('#fb4934', 'accent'), 'green': ('#b8bb26', 'accent'),
               'yellow': ('#fabd2f', 'accent'), 'blue': ('#83a598', 'accent'),
               'purple': ('#d3869b', 'accent'), 'aqua': ('#8ec07c', 'accent'),
               'orange': ('#fe8019', 'accent')}),
    'gruvbox-dark-fixed': dict(
        mode='dark', bg='#282828', colour='#fe8019', contender=True, variant=True,
        source='this repo (gruvbox-dark ports; not upstream)',
        intent='Shipped as themes/*/gruvbox-dark. Same 0.004-step lightness repair as '
               'elsewhere in this report: red #fb4934 to #fb5440 (2.4% dL) and gray '
               '#928374 to #9a8c7e (3.6% dL). Hue and saturation untouched. Claude maps '
               'the pair onto inactive, error, diffRemoved, diffRemovedWord, '
               'red_FOR_SUBAGENTS_ONLY, and rainbow_red. Upstream vanilla stays in '
               'gruvbox-dark for the baseline.',
        roles={'fg': ('#ebdbb2', 'body'), 'gray': ('#9a8c7e', 'dim'),
               'red': ('#fb5440', 'accent'), 'green': ('#b8bb26', 'accent'),
               'yellow': ('#fabd2f', 'accent'), 'blue': ('#83a598', 'accent'),
               'purple': ('#d3869b', 'accent'), 'aqua': ('#8ec07c', 'accent'),
               'orange': ('#fe8019', 'accent')}),
    'everforest-dark-med': dict(
        mode='dark', bg='#2d353b', colour='#a7c080', contender=True,
        source='sainnhe/everforest palette.md',
        intent='Green-grey "forest" surfaces, warm cream foreground.',
        roles={'fg': ('#d3c6aa', 'body'), 'grey1': ('#859289', 'dim'),
               'red': ('#e67e80', 'accent'), 'orange': ('#e69875', 'accent'),
               'yellow': ('#dbbc7f', 'accent'), 'green': ('#a7c080', 'accent'),
               'aqua': ('#83c092', 'accent'), 'blue': ('#7fbbb3', 'accent'),
               'purple': ('#d699b6', 'accent')}),
    'primer-dark': dict(
        mode='dark', bg='#0d1117', colour='#58a6ff', contender=False,
        source='primer/primitives syntax.json5 ansi block',
        intent='Audited UI system. ANSI black/white dropped as surface roles.',
        roles={'white': ('#f0f6fc', 'body'), 'gray': ('#656c76', 'dim'),
               'red': ('#ff7b72', 'accent'), 'redBright': ('#ffa198', 'accent'),
               'green': ('#3fb950', 'accent'), 'greenBright': ('#56d364', 'accent'),
               'yellow': ('#d29922', 'accent'), 'yellowBright': ('#e3b341', 'accent'),
               'blue': ('#58a6ff', 'accent'), 'blueBright': ('#79c0ff', 'accent'),
               'magenta': ('#be8fff', 'accent'),
               'magentaBright': ('#d2a8ff', 'accent')}),
}

# Where each palette's hexes actually come from. `palette_url` is the page the
# measured values were read from; `repo` is the scheme's own source repository.
PALETTE_URLS = {
    'modus-operandi': dict(palette_url='https://protesilaos.com/emacs/modus-themes-colors',
                           repo='https://git.sr.ht/~protesilaos/modus-themes'),
    'flexoki-light': dict(palette_url='https://stephango.com/flexoki',
                          repo='https://github.com/kepano/flexoki'),
    'gruvbox-light': dict(palette_url='https://github.com/morhetz/gruvbox',
                          repo='https://github.com/morhetz/gruvbox'),
    'catppuccin-latte': dict(palette_url='https://github.com/catppuccin/palette',
                             repo='https://github.com/catppuccin/palette'),
    'everforest-light-med': dict(palette_url='https://github.com/sainnhe/everforest',
                                 repo='https://github.com/sainnhe/everforest'),
    'everforest-light-soft': dict(palette_url='https://github.com/sainnhe/everforest',
                                  repo='https://github.com/sainnhe/everforest'),
    'primer-light': dict(palette_url='https://github.com/primer/primitives',
                         repo='https://github.com/primer/primitives'),
    'catppuccin-mocha': dict(palette_url='https://github.com/catppuccin/palette',
                             repo='https://github.com/catppuccin/palette'),
    'flexoki-dark': dict(palette_url='https://stephango.com/flexoki',
                         repo='https://github.com/kepano/flexoki'),
    'gruvbox-dark': dict(palette_url='https://github.com/morhetz/gruvbox',
                         repo='https://github.com/morhetz/gruvbox'),
    'gruvbox-dark-fixed': dict(palette_url='https://github.com/morhetz/gruvbox',
                               repo='https://github.com/morhetz/gruvbox'),
    'everforest-dark-med': dict(palette_url='https://github.com/sainnhe/everforest',
                                repo='https://github.com/sainnhe/everforest'),
    'primer-dark': dict(palette_url='https://github.com/primer/primitives',
                        repo='https://github.com/primer/primitives'),
}

# Slug of the shipped theme for each report palette that this repo ports with
# the 0.004-step repair. Vanilla stays in PALETTES as the baseline card.
SHIPPED_FIXED = {
    'flexoki-light': 'flexoki-light',
    'flexoki-dark': 'flexoki-dark',
    'gruvbox-light': 'gruvbox-light',
    'catppuccin-latte': 'catppuccin-latte',
    'everforest-light-med': 'everforest-light',
    'everforest-dark-med': 'everforest-dark',
    'gruvbox-dark': 'gruvbox-dark',
    'primer-light': 'primer-light',
    'primer-dark': 'primer-dark',
}


def _derive_fixed(key, p):
    slug = SHIPPED_FIXED.get(key)
    if not slug:
        return None
    roles = {}
    bits = []
    colour = p['colour']
    for name, (hx, kind) in p['roles'].items():
        if wcag(hx, p['bg']) < 4.5:
            cand, d = repair_cost(hx, p['bg'])
            roles[name] = (cand, kind)
            bits.append('%s %s to %s (%.1f%% dL)' % (name, hx, cand, (d or 0) * 100))
            if hx.lower() == p['colour'].lower():
                colour = cand
        else:
            roles[name] = (hx, kind)
    if not bits:
        return None
    return dict(
        mode=p['mode'], bg=p['bg'], colour=colour, contender=True, variant=True,
        badge='shipped',
        source='this repo (%s ports; not upstream)' % slug,
        intent=('Shipped as themes/*/%s. Same 0.004-step lightness repair as '
                'elsewhere in this report: %s. Hue and saturation untouched.'
                % (slug, '; '.join(bits))),
        roles=roles,
    )


def _inject_fixed(palettes):
    out = {}
    for k, p in palettes.items():
        if (k + '-fixed') not in palettes and not p.get('variant'):
            fx = _derive_fixed(k, p)
            if fx:
                out[k + '-fixed'] = fx
        out[k] = p
    return out


PALETTES = _inject_fixed(PALETTES)
for _k in list(PALETTES):
    if _k.endswith('-fixed') and _k not in PALETTE_URLS:
        PALETTE_URLS[_k] = PALETTE_URLS[_k[:-6]]

# Reference list rendered as the artifact's "Scheme sources" section. One entry
# per scheme, not per palette: gruvbox dark and light are one repository.
SCHEME_SOURCES = [
    ('Modus Operandi', 'Protesilaos Stavrou',
     'https://protesilaos.com/emacs/modus-themes-colors',
     'https://git.sr.ht/~protesilaos/modus-themes'),
    ('Flexoki', 'Steph Ango',
     'https://stephango.com/flexoki', 'https://github.com/kepano/flexoki'),
    ('Gruvbox', 'Pavel Pertsev (morhetz)',
     'https://github.com/morhetz/gruvbox', 'https://github.com/morhetz/gruvbox'),
    ('Catppuccin', 'Catppuccin community',
     'https://github.com/catppuccin/palette', 'https://github.com/catppuccin/palette'),
    ('Everforest', 'sainnhe',
     'https://github.com/sainnhe/everforest', 'https://github.com/sainnhe/everforest'),
    ('GitHub Primer', 'GitHub',
     'https://github.com/primer/primitives', 'https://github.com/primer/primitives'),
    ('Radix Colors', 'WorkOS',
     'https://github.com/radix-ui/colors', 'https://github.com/radix-ui/colors'),
]


def scheme_links():
    out = []
    for name, author, page, repo in SCHEME_SOURCES:
        same = page.rstrip('/') == repo.rstrip('/')
        links = ('<a href="%s" rel="noopener" target="_blank">source</a>'
                 % escape(page))
        if not same:
            links += (' &middot; <a href="%s" rel="noopener" target="_blank">repo</a>'
                      % escape(repo))
        out.append('<li><b>%s</b> &middot; %s &mdash; %s</li>'
                   % (escape(name), escape(author), links))
    return '\n'.join(out)


# Two weightings over the same seven measured axes. Axes are measurements; only
# the weights differ. `contrast` is a compliance-flavoured view that deliberately
# ignores colour. `session` is the long-session view: comfort and colour count.
PROFILES: dict[str, dict] = {
    'contrast': dict(label='Contrast-first', short='contrast',
                     note='compliance view; colour scores zero',
                     weights={'body': 0.20, 'dim': 0.20, 'worst': 0.20, 'pass': 0.15,
                              'color': 0.00, 'comfort': 0.10, 'repair': 0.15}),
    'session': dict(label='Long-session', short='session',
                    note='comfort and colour count',
                    weights={'body': 0.15, 'dim': 0.15, 'worst': 0.15, 'pass': 0.10,
                             'color': 0.20, 'comfort': 0.15, 'repair': 0.10}),
}


def clamp01(v):
    return max(0.0, min(1.0, v))


def oklab(hexv):
    """sRGB -> Oklab (Björn Ottosson). Returns (L, a, b)."""
    r, g, b = (srgb_lin(c) for c in hex2rgb(hexv))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (x ** (1 / 3) if x > 0 else -((-x) ** (1 / 3)) for x in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def colour_axes(accents):
    """Hedonic chroma level and functional accent separability, both 0-100.

    Chroma: mean Oklab C over accents, mapped from the observed 0.08-0.20 band.
    Separability: worst pairwise Oklab distance, mapped from 0.04-0.06. A palette
    whose two accents land 0.045 apart cannot separate a string from a keyword
    even if its mean chroma is respectable (Everforest dark is the case in point).
    """
    labs = [oklab(x['hex']) for x in accents]
    chromas = [math.hypot(a, b) for _l, a, b in labs]
    pairs = [math.dist(labs[i], labs[j]) for i in range(len(labs))
             for j in range(i + 1, len(labs))]
    mean_chroma = sum(chromas) / len(chromas)
    worst_pair = min(pairs) if pairs else 0.0
    chroma_score = clamp01((mean_chroma - 0.08) / 0.12) * 100
    separate_score = clamp01((worst_pair - 0.04) / 0.06) * 100
    return dict(chroma=mean_chroma, worst_pair=worst_pair,
                chroma_score=chroma_score, separate_score=separate_score,
                score=0.6 * chroma_score + 0.4 * separate_score)


# ------------------------------------------------------------------- analysis
# APCA gates. In 0.1.9, Lc 60 is the content-text floor and 75 the body-text
# floor; in dark mode ~95 is a ceiling, not a target. WCAG 2.1 is polarity-blind
# and saturates at 4.5:1, so both standards gate every accent term.
APCA_CONTENT_FLOOR = 60.0
APCA_BODY_FLOOR = 75.0
APCA_DARK_CEILING = 95.0


def apca_scale(lc):
    """Lc magnitude as a share of the APCA content floor: 60 reads as full marks.

    Deliberately not a 45→0 / 75→100 window: a hard floor at 45 zeroed whole
    axes for palettes whose accents sit just under it, which reads as "broken"
    rather than "below the floor". A proportional share keeps the ranking
    ordered and stays interpretable.
    """
    return max(0.0, min(100.0, abs(lc) / APCA_CONTENT_FLOOR * 100.0))


def analyse(key, p) -> dict:
    bg = p['bg']
    dark = p['mode'] == 'dark'
    roles = []
    for name, (hexv, kind) in p['roles'].items():
        r, lc = wcag(hexv, bg), apca(hexv, bg)
        roles.append(dict(name=name, hex=hexv, kind=kind, ratio=r, lc=lc,
                          rel=rel_lum(hex2rgb(hexv))))
    body = next(x for x in roles if x['kind'] == 'body')
    dim = next(x for x in roles if x['kind'] == 'dim')
    accents = [x for x in roles if x['kind'] == 'accent']
    fails = [x for x in accents if x['ratio'] < 4.5]
    fails_apca = [x for x in accents if abs(x['lc']) < APCA_CONTENT_FLOOR]
    pass_both = [x for x in accents
                 if x['ratio'] >= 4.5 and abs(x['lc']) >= APCA_CONTENT_FLOOR]
    worst_lc = min(abs(x['lc']) for x in accents)
    repairs = []
    for x in sorted(fails, key=lambda y: y['ratio']):
        cand, d = repair_cost(x['hex'], bg)
        repairs.append(dict(name=x['name'], orig=x['hex'], ratio=x['ratio'],
                            cand=cand, newratio=wcag(cand, bg) if cand else None,
                            delta=(d or 0) * 100))
    max_repair = max([r['delta'] for r in repairs], default=0.0)
    span = max(x['rel'] for x in roles) - rel_lum(hex2rgb(bg))
    peak = max(roles, key=lambda x: x['rel'])

    if dark:
        body_score = body['ratio'] / 21 * 100
        dim_score = min(100, abs(dim['lc']) / 75 * 100)
        comfort = max(0.0, min(100.0, (1 - span / 0.90) * 100))
        comfort_label = 'halation headroom'
        comfort_note = 'peak foreground span %.3f' % span
    else:
        body_score = body['ratio'] / 21 * 100
        dim_score = min(100, dim['ratio'] / 7 * 100)
        bgrel = rel_lum(hex2rgb(bg))
        comfort = max(0.0, min(100.0, (1 - bgrel) / 0.12 * 100))
        comfort_label = 'glare headroom'
        comfort_note = 'surface relLum %.4f' % bgrel

    colour = colour_axes(accents)
    body_axis = min(100.0, body_score)
    if dark:
        # Past the ceiling more light is not more readable; it blooms.
        over = max(0.0, abs(body['lc']) - APCA_DARK_CEILING)
        body_axis = min(body_axis, max(0.0, 100.0 - over / 15.0 * 100.0))
    axes = {
        'body': body_axis,
        'dim': dim_score,
        # Weakest link across both standards, so a 12:1 accent that blooms or a
        # 5:1 accent hovering at the APCA floor cannot saturate the term.
        'worst': min(min(100.0, min(x['ratio'] for x in accents) / 4.5 * 100),
                     apca_scale(worst_lc)),
        'pass': len(pass_both) / len(accents) * 100,
        'color': colour['score'],
        'comfort': comfort,
        'repair': max(0.0, 100 - max_repair / 25 * 100),
    }
    scores = {name: sum(axes[k] * w for k, w in profile['weights'].items())
              for name, profile in PROFILES.items()}
    return dict(key=key, roles=roles, body=body, dim=dim, accents=accents,
                fails=fails, fails_apca=fails_apca, pass_both=pass_both,
                worst_lc=worst_lc, repairs=repairs, max_repair=max_repair,
                axes=axes, scores=scores, score=scores['session'], col=colour,
                span=span, peak=peak,
                comfort_label=comfort_label, comfort_note=comfort_note,
                dark=dark, **{k: v for k, v in p.items() if k != 'roles'})


AXIS_LABELS = {
    'light': [('body', 'body text'), ('dim', 'dim text'), ('worst', 'worst accent'),
              ('color', 'colour'), ('pass', 'accents pass both'),
              ('comfort', 'glare headroom'), ('repair', 'repairability')],
    'dark': [('body', 'body text'), ('dim', 'dim text (APCA)'), ('worst', 'worst accent'),
             ('color', 'colour'), ('pass', 'accents pass both'),
             ('comfort', 'halation headroom'), ('repair', 'repairability')],
}


# ------------------------------------------------------------------------ svg
# Series colour is the palette's own accent, so two similar palettes (gruvbox and
# Everforest light are both olive) can be indistinguishable. Dash pattern is the
# second channel; keep the order stable so the legend matches the plot.
DASHES = ('', '7 3', '2 3', '10 3 2 3', '1 3', '5 2 1 2')


def radar(mode, series):
    # Labels sit in reserved margins, rather than extending beyond a tight plot.
    # Seven axes now, so geometry is computed from the count instead of a table of
    # fixed positions; light and dark must stay dimensionally identical.
    axes = AXIS_LABELS[mode]
    n = len(axes)
    sx, sy, cx, cy, radius = 520, 400, 260, 190, 118
    label_r = radius + 26
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {sx} {sy}" '
             f'class="radar" role="img" aria-labelledby="radar-{mode}">',
             f'<title id="radar-{mode}">{mode.title()} contenders: {n} axes, 0–100</title>']

    def point(i, value):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        return cx + radius * value * math.cos(angle), cy + radius * value * math.sin(angle)

    for value in (0.25, 0.5, 0.75, 1.0):
        points = ' '.join('%.2f,%.2f' % point(i, value) for i in range(n))
        parts.append(f'<polygon points="{points}" class="ring"/>')
        # No "100" tick: it collides with the top axis label and the outer ring
        # already reads as full scale.
        if value < 1.0:
            parts.append(f'<text x="{cx + 5}" y="{cy - radius * value - 4}" '
                         f'class="tick">{value * 100:.0f}</text>')
    parts.append(f'<text x="{cx + 5}" y="{cy + 14}" class="tick">0</text>')
    for i in range(n):
        x, y = point(i, 1)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.2f}" y2="{y:.2f}" class="spoke"/>')
    for index, palette in enumerate(series):
        points = ' '.join('%.2f,%.2f' % point(i, palette['axes'][key] / 100)
                          for i, (key, _) in enumerate(axes))
        color = palette['colour']
        if palette.get('variant'):
            # A derived variant reads as an outline so it cannot be mistaken for
            # an independent palette in the same plot.
            dash, fill, width = '2 3', '0', '2.5'
        else:
            dash, fill, width = DASHES[index % len(DASHES)], '.13', '2'
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
        parts.append(f'<polygon points="{points}" data-series="{index}" '
                     f'fill="{color}" fill-opacity="{fill}" '
                     f'stroke="{color}" stroke-width="{width}"{dash_attr}>'
                     f'<title>{palette["key"]}</title></polygon>')
    for i, (_key, label) in enumerate(axes):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        x = cx + label_r * math.cos(angle)
        y = cy + label_r * math.sin(angle) + 4
        cos = math.cos(angle)
        anchor = 'middle' if abs(cos) < 0.35 else ('start' if cos > 0 else 'end')
        # Two short lines keep even the longest label inside the viewBox.
        words = label.split(' ', 1)
        lines = ''.join(f'<tspan x="{x:.1f}" dy="{0 if w == 0 else 14}">{escape(word)}</tspan>'
                        for w, word in enumerate(words))
        parts.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
                     f'class="axis-label">{lines}</text>')
    parts.append('</svg>')
    return '\n'.join(parts)


def variant_ref(s):
    if not s.get('variant'):
        return ''
    return ' <span class="ref">%s</span>' % escape(s.get('badge', 'shipped'))


def legend(series):
    out = ['<ul class="legend">']
    for index, s in enumerate(series):
        dash = '2 3' if s.get('variant') else DASHES[index % len(DASHES)]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
        # data-series matches the polygon, so hovering a row can isolate it in the
        # plot. Keyboard users get the same behaviour through focus.
        out.append('<li data-series="%d" tabindex="0" title="isolate %s">'
                   '<svg class="swatch-line" width="24" height="8" '
                   'aria-hidden="true"><line x1="1" y1="4" x2="23" y2="4" '
                   f'stroke="{s["colour"]}" stroke-width="2.5"{dash_attr}/></svg>'
                   '<span class="lg-name">%s%s</span>'
                   '<span class="lg-score">%.1f</span></li>'
                   % (index, s['key'], s['key'],
                      variant_ref(s),
                      s['score']))
    out.append('</ul>')
    return '\n'.join(out)


ISOLATE_JS = """
(function(){
  var charts = document.querySelectorAll('.chart');
  Array.prototype.forEach.call(charts, function(chart){
    var svg = chart.querySelector('svg.radar');
    if (!svg) { return; }
    var polys = svg.querySelectorAll('polygon[data-series]');
    function isolate(idx){
      svg.classList.add('isolating');
      Array.prototype.forEach.call(polys, function(p){
        p.classList.toggle('hot', p.getAttribute('data-series') === idx);
      });
    }
    function restore(){
      svg.classList.remove('isolating');
      Array.prototype.forEach.call(polys, function(p){ p.classList.remove('hot'); });
    }
    Array.prototype.forEach.call(
      chart.querySelectorAll('.legend li[data-series]'),
      function(row){
        var idx = row.getAttribute('data-series');
        row.addEventListener('mouseenter', function(){ isolate(idx); });
        row.addEventListener('mouseleave', restore);
        row.addEventListener('focus', function(){ isolate(idx); });
        row.addEventListener('blur', restore);
      });
  });
})();
"""

# Click-to-sort for the leaderboards. Each tbody sorts on its own, so reference
# rows stay below their divider. data-v overrides a cell's text as its sort
# value; '—' counts as missing and sinks in both directions.
SORT_JS = r"""
(function(){
  var NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)$/;
  function value(cell){
    if (cell.hasAttribute('data-v')) { return cell.getAttribute('data-v'); }
    var text = cell.textContent.trim();
    return text === '—' ? '' : text;
  }
  function dataRows(body){
    return Array.prototype.filter.call(body.rows, function(row){ return row.cells[0].tagName === 'TD'; });
  }
  Array.prototype.forEach.call(document.querySelectorAll('table.sortable'), function(table){
    Array.prototype.forEach.call(table.tBodies, function(body){
      dataRows(body).forEach(function(row, i){ row.setAttribute('data-base', i); });
    });
    function sortTable(index, direction){
      Array.prototype.forEach.call(table.tBodies, function(body){
        var rows = dataRows(body);
        var numeric = rows.every(function(row){
          var v = value(row.cells[index]); return v === '' || NUMBER.test(v);
        });
        var items = rows.map(function(row){
          var v = value(row.cells[index]);
          return {row: row, missing: v === '', base: +row.getAttribute('data-base'),
                  v: v === '' ? '' : (numeric ? parseFloat(v) : v.toLowerCase())};
        });
        items.sort(function(a, b){
          if (a.missing !== b.missing) { return a.missing ? 1 : -1; }
          if (a.v !== b.v) { var c = a.v < b.v ? -1 : 1; return direction === 'down' ? -c : c; }
          return a.base - b.base;
        });
        items.forEach(function(item){ body.appendChild(item.row); });
      });
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function(th, i){
        th.setAttribute('aria-sort', i !== index ? 'none'
          : (direction === 'down' ? 'descending' : 'ascending'));
      });
    }
    var current = {index: -1, direction: 'up'};
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function(th, index){
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'sort';
      while (th.firstChild) { button.appendChild(th.firstChild); }
      th.appendChild(button);
      th.setAttribute('aria-sort', 'none');
      button.addEventListener('click', function(){
        var direction = current.index === index
          ? (current.direction === 'down' ? 'up' : 'down')
          : (th.getAttribute('data-first') || 'up');
        current = {index: index, direction: direction};
        sortTable(index, direction);
      });
    });
  });
})();
"""


# --------------------------------------------------------- terminal simulation
ANSI_ALIASES = {
    'magenta': ('magenta', 'purple', 'mauve', 'pink'),
    'cyan': ('cyan', 'aqua', 'teal'),
}


def ansi_entries(s):
    """Map a palette's own accents onto the 8 canonical ANSI roles.

    Upstream palettes publish 6-9 accents, not a 16-colour ANSI table, so the
    mapping is by role name (magenta<-purple/mauve, cyan<-aqua/teal, white<-body,
    black<-dim). Anything left over is shown as an extra swatch rather than
    silently dropped.
    """
    accents = {r['name']: r for r in s['accents']}

    def pick(*names):
        for name in names:
            if name in accents:
                return accents[name]
        return None

    rows = [('black', s['dim']), ('red', pick('red')), ('green', pick('green')),
            ('yellow', pick('yellow')), ('blue', pick('blue')),
            ('magenta', pick(*ANSI_ALIASES['magenta'])),
            ('cyan', pick(*ANSI_ALIASES['cyan'])), ('white', s['body'])]
    rows = [(name, role) for name, role in rows if role]
    used = {id(role) for _name, role in rows}
    extra = [role for role in s['accents'] if id(role) not in used]
    return rows, extra


def shift_lightness(hexv, dark, amount=0.10):
    """Derive a 'bright' variant: same hue/sat, lightness moved away from the bg."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in hex2rgb(hexv)))
    l2 = max(0.0, min(1.0, l + (amount if dark else -amount)))
    return '#%02x%02x%02x' % tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l2, s))


def terminal_preview(s):
    rows, extra = ansi_entries(s)
    col = {name: role['hex'] for name, role in rows}
    ratio = {name: role['ratio'] for name, role in rows}
    dark = s['dark']
    body, dim = s['body']['hex'], s['dim']['hex']
    worst_accent = min(r['ratio'] for r in s['accents'])
    failing = len(s['fails'])
    surface_metric = (('span %.3f' % s['span']) if dark
                      else ('surface relLum %.4f' % rel_lum(hex2rgb(s['bg']))))
    risk = []
    if failing:
        risk.append('%d accent%s under 4.5:1' % (failing, '' if failing == 1 else 's'))
    if dark and abs(s['body']['lc']) > 95:
        risk.append('halation risk')

    def swatches():
        out = ['<div class="swatches" role="img" aria-label="ANSI palette">']
        for name, role in rows:
            out.append('<i style="background:%s" title="%s %s · %.2f:1"></i>'
                       % (role['hex'], name, role['hex'], role['ratio']))
        for name, role in rows:
            bright = shift_lightness(role['hex'], dark)
            out.append('<i class="derived" style="background:%s" title="bright %s (derived) '
                       '%s"></i>' % (bright, name, bright))
        for role in extra:
            out.append('<i style="background:%s" title="%s %s · %.2f:1"></i>'
                       % (role['hex'], role['name'], role['hex'], role['ratio']))
        out.append('</div>')
        return ''.join(out)

    lines = [
        '<span style="color:%s">noomz@mbp</span> <span style="color:%s">~/P/Opensources/noomz-themes</span>'
        % (col['green'], col['blue']),
        '<span style="color:%s">&#10095;</span> rg -n "contrast" scripts/ | head -2' % dim,
        '<span style="color:%s">scripts/palette-report.py</span>:<span style="color:%s">351</span>:'
        ' <span style="color:%s">comfort = clamp((1 - span / 0.90) * 100)</span>'
        % (col['yellow'], col['magenta'], body),
        '<span style="color:%s">+ page_text broken at 3.1:1, repair before port</span>' % col['green'],
        '<span style="color:%s">- canonical accent kept for identity</span>' % col['red'],
        '<span style="color:%s">warning</span> <span style="color:%s">weakest accent here is '
        '%.2f:1</span>' % (col['yellow'], body, worst_accent),
        '<span style="color:%s">error</span> <span style="color:%s">diff render aborted, token '
        'unknown</span>' % (col['red'], body),
        '<span style="color:%s">claude</span> <span style="color:%s">&#183; 3 files changed '
        '&#183; 12s</span>' % (col['magenta'], dim),
    ]
    body_lines = '\n'.join('<div class="ln">%s</div>' % line for line in lines)
    chips = ' '.join('<span class="riskchip">%s</span>' % r for r in risk)
    return ('''<figure class="term">
<figcaption><code>%s</code> <span class="tmeta">body %.2f:1 &middot; dim %.2f:1 &middot;
worst accent %.2f:1 &middot; %s</span>%s</figcaption>
<div class="screen" style="background:%s;color:%s">%s%s</div>
</figure>''' % (s['key'], s['body']['ratio'], s['dim']['ratio'], worst_accent,
               surface_metric, (' ' + chips) if chips else '',
               s['bg'], body, body_lines, swatches()))


# ----------------------------------------------------------------------- html
def flag_cells(row, dark):
    ratio, lc = row['ratio'], row['lc']
    band = 'AAA' if ratio >= 7 else ('AA' if ratio >= 4.5 else 'FAIL')
    flags = []
    if dark and abs(lc) > 95:
        flags.append('halation')
    elif abs(lc) >= 75:
        flags.append('Lc75+')
    elif abs(lc) >= 60:
        flags.append('Lc60+')
    else:
        flags.append('Lc&lt;60')
    cls = {'AAA': 'ok', 'AA': 'mid', 'FAIL': 'bad'}[band]
    return ('<td class="num">%.4f</td><td class="num">%+.2f</td>'
            '<td><span class="pill %s">%s</span> %s</td>'
            % (ratio, lc, cls, band,
               ' '.join('<span class="flag">%s</span>' % f for f in flags)))


def palette_card(s):
    rows = ['<table class="roles"><thead><tr><th>role</th><th>hex</th>'
            '<th class="num">WCAG</th><th class="num">APCA</th><th>verdict</th>'
            '</tr></thead><tbody>']
    for r in s['roles']:
        rows.append('<tr><td><code>%s</code><br><span class="note">%s</span></td>'
                    '<td><span class="chip" style="background:%s"></span><code>%s</code></td>%s</tr>'
                    % (r['name'], r['kind'], r['hex'], r['hex'], flag_cells(r, s['dark'])))
    rows.append('</tbody></table>')
    if s['repairs']:
        items = ''.join(
            f'<tr><td><code>{r["name"]}</code></td>'
            f'<td><span class="chip" style="background:{r["orig"]}"></span><code>{r["orig"]}</code></td>'
            f'<td class="num">{r["ratio"]:.4f}</td>'
            f'<td><span class="chip" style="background:{r["cand"]}"></span><code>{r["cand"]}</code></td>'
            f'<td class="num">{r["newratio"]:.4f}</td><td class="num">{r["delta"]:.1f}</td></tr>'
            for r in s['repairs'])
        rep = ('<div class="repair"><h4>Identity cost to reach 4.5:1</h4>'
               '<div class="table-scroll"><table class="repairs"><thead><tr>'
               '<th>accent</th><th>original</th><th class="num">WCAG</th>'
               '<th>repaired</th><th class="num">WCAG</th><th class="num">ΔL × 100</th>'
               '</tr></thead><tbody>' + items + '</tbody></table></div>'
               '<p class="note">HLS lightness movement estimates identity cost. '
               'Small changes may suit a port; large changes may warrant a documented '
               '<code>-contrast</code> variant. This is not a perceptual difference measurement.</p></div>')
    else:
        rep = ('<div class="repair"><h4>Identity cost to reach 4.5:1</h4>'
               f'<p class="note">All accents already pass; max repair cost {s["max_repair"]:.1f} ΔL × 100.</p></div>')
    axes = ''.join('<li><b>%.0f</b> %s</li>' % (s['axes'][k], label)
                   for k, label in AXIS_LABELS[s['mode']])
    axes = ('<li><b>%.1f</b> contrast-first score</li>' % s['scores']['contrast']) + axes
    colour_note = ('<p class="note">colour: mean Oklab chroma %.3f (%.0f/100) &middot; '
                   'worst accent pair &Delta;E %.3f (%.0f/100) &middot; blended %.0f/100</p>'
                   % (s['col']['chroma'], s['col']['chroma_score'],
                      s['col']['worst_pair'], s['col']['separate_score'],
                      s['axes']['color']))
    badge = '' if s['contender'] else ' <span class="ref">reference</span>'
    if s.get('variant'):
        badge += variant_ref(s)
    links = PALETTE_URLS[s['key']]
    src_link = '<a href="%s" rel="noopener" target="_blank">%s</a>' % (
        escape(links['palette_url']), escape(s['source']))
    repo_link = ('<a class="repolink" href="%s" rel="noopener" target="_blank">'
                 'repo&nbsp;&#8599;</a>' % escape(links['repo']))
    return ('''<article class="card" id="%s">
<h3>%s%s <span class="scorebadge">%.1f</span></h3>
<p class="meta">bg <code>%s</code> &middot; %s &middot; %s %s</p>
<p class="intent">%s</p>
<ul class="axescore">%s</ul>
%s
%s
%s
</article>''' % (s['key'], s['key'], badge, s['scores']['session'], s['bg'],
                 'negative polarity' if s['dark'] else 'positive polarity',
                 src_link, repo_link,
                 escape(s['intent']), axes, colour_note,
                 '<div class="table-scroll">' + '\n'.join(rows) + '</div>', rep))


def leaderboard(rows, title, subtitle):
    dark = rows[0]['dark']
    surface_heading = 'peak span' if dark else 'surface relLum'
    # Contrast-first rank is shown alongside so the reorder is visible, not hidden.
    contrast_ranks = {p['key']: i for i, p in enumerate(
        sorted([r for r in rows if r['contender']],
               key=lambda r: -r['scores']['contrast']), 1)}
    # data-first="down" marks higher-is-better columns: their first click sorts
    # best first. Rank, surface and repair columns sort ascending first.
    down = ' data-first="down"'
    out = ['<div class="table-scroll"><table class="board sortable"><thead><tr><th>#</th><th>palette</th>'
           f'<th class="num"{down}>long-<br>session</th><th class="num"{down}>contrast-<br>first</th>'
           '<th class="num">contrast<br>rank</th>'
           f'<th class="num"{down}>body</th><th class="num"{down}>dim</th>'
           f'<th class="num"{down}>worst accent</th><th class="num"{down}>accents<br>≥4.5:1</th>'
           f'<th class="num"{down}>accents<br>Lc≥60</th><th class="num"{down}>worst<br>Lc</th>'
           f'<th class="num"{down}>colour</th><th class="num">{surface_heading}</th>'
           '<th class="num">max repair<br>ΔL × 100</th>'
           '</tr></thead><tbody>']
    rank = 0
    reference_started = False
    for palette in rows:
        if palette['contender']:
            rank += 1
            rank_label = str(rank)
            c_rank = str(contrast_ranks[palette['key']])
        else:
            rank_label = '—'
            c_rank = '—'
            if not reference_started:
                out.append('</tbody><tbody class="references"><tr><th colspan="14">Reference only · unranked</th></tr>')
                reference_started = True
        surface = palette['span'] if dark else rel_lum(hex2rgb(palette['bg']))
        delta = palette['scores']['session'] - palette['scores']['contrast']
        vb = variant_ref(palette)
        n = len(palette['accents'])
        passing = n - len(palette['fails'])
        out.append(
            f'<tr><td class="num">{rank_label}</td><td data-v="{palette["key"]}"><span class="chip" '
            f'style="background:{palette["colour"]}"></span>'
            f'<a href="#{palette["key"]}"><code>{palette["key"]}</code></a>{vb}</td>'
            f'<td class="num strong">{palette["scores"]["session"]:.1f}</td>'
            f'<td class="num" data-v="{palette["scores"]["contrast"]:.1f}">'
            f'{palette["scores"]["contrast"]:.1f} '
            f'<span class="delta{" up" if delta > 0.5 else (" down" if delta < -0.5 else "")}">'
            f'{delta:+.1f}</span></td>'
            f'<td class="num dimtxt">{c_rank}</td>'
            f'<td class="num">{palette["body"]["ratio"]:.4f}</td>'
            f'<td class="num">{palette["dim"]["ratio"]:.4f}</td>'
            f'<td class="num">{min(r["ratio"] for r in palette["accents"]):.4f}</td>'
            f'<td class="num" data-v="{passing / n:.4f}">{passing}/{n}</td>'
            f'<td class="num" data-v="{len(palette["pass_both"]) / n:.4f}">{len(palette["pass_both"])}/{n}</td>'
            f'<td class="num">{palette["worst_lc"]:.1f}</td>'
            f'<td class="num">{palette["axes"]["color"]:.0f}</td>'
            f'<td class="num">{surface:.4f}</td><td class="num">{palette["max_repair"]:.1f}</td></tr>')
    out.append('</tbody></table></div>')
    return (f'<section class="lb"><h3>{title}</h3><p class="note">{subtitle}</p>'
            + '\n'.join(out) + '</section>')


# Radix Colors opaque CSS inputs: (step 2, step 11, step 12).
# These reproduce the original draft's check without storing measured Lc values.
RADIX = {
    'light': {'gray': ('#f9f9f9', '#646464', '#202020'),
              'blue': ('#f4faff', '#0d74ce', '#113264'),
              'tomato': ('#fff8f7', '#d13415', '#5c271f')},
    'dark': {'gray': ('#191919', '#b4b4b4', '#eeeeee'),
             'blue': ('#111927', '#70b8ff', '#c2e6ff'),
             'tomato': ('#1f1513', '#ff977d', '#fbd3cb')},
}


def radix_table():
    rows = []
    for mode, scales in RADIX.items():
        for scale, (bg, step11, step12) in scales.items():
            cells = []
            for color, target in ((step11, 60), (step12, 90)):
                lc = apca(color, bg)
                passed = abs(lc) >= target
                band = 'ok' if passed else 'bad'
                caution = ' · halation signal' if mode == 'dark' and abs(lc) > 95 else ''
                cells.append(f'<td class="num">{lc:+.2f}</td><td><span class="pill {band}">'
                             f'{"pass" if passed else "miss"}</span>{caution}</td>')
            rows.append(f'<tr><td><code>{scale}</code></td><td>{mode}</td>'
                        f'<td><code>{bg}</code></td><td><code>{step11}</code></td>'
                        f'<td><code>{step12}</code></td>' + ''.join(cells) + '</tr>')
    return ('<div class="table-scroll"><table class="board"><thead><tr><th>scale</th><th>mode</th>'
            '<th>step 2</th><th>step 11</th><th>step 12</th><th class="num">11 Lc</th>'
            '<th>target 60</th><th class="num">12 Lc</th><th>target 90</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


CSS = """
a{color:inherit;text-underline-offset:3px}
.table-scroll{overflow-x:auto;max-width:100%}
.card,.chart{min-width:0}
.lb + .lb{margin-top:24px}
.references{border-top:3px solid #777;background:#f3f1e9}
.references th{color:var(--ink)}
.tick{font-size:10px;fill:#666}
.repairs{font-size:11px}
.repairs th,.repairs td{padding:5px 4px}

:root{--ink:#1b1b1b;--dim:#6b6b6b;--line:#e2e0d8;--paper:#fbfaf6;
--accent:#8a2b1f;--ok:#1a6b2f;--mid:#8a6b00;--bad:#a8261c}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1384px;margin:0 auto;padding:48px 28px 80px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:20px;margin:44px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:16px;margin:0 0 4px}
h4{font-size:13px;margin:14px 0 6px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim)}
p{margin:0 0 10px}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
.sub{color:var(--dim);margin:0 0 26px;font-size:14px}
.verdict{background:#fff;border:1px solid var(--line);border-left:3px solid var(--accent);
padding:18px 20px;margin:0 0 8px}
.verdict strong{font-size:15px}
.note{color:var(--dim);font-size:13px}
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:26px}
@media(max-width:880px){.grid{grid-template-columns:1fr}}
.chart{background:#fff;border:1px solid var(--line);padding:12px}
.radar{width:100%;height:auto;display:block}
.ring{fill:none;stroke:var(--line);stroke-width:1}
.ring.outer{stroke:#cfccc0}
.spoke{stroke:var(--line);stroke-width:1}
.axis-label{font-size:12px;fill:#555;letter-spacing:.01em}
.legend{list-style:none;padding:0;margin:10px 0 0;font-size:13px}
.legend li{display:flex;align-items:center;gap:8px;padding:2px 4px;margin-left:-4px;
border-radius:4px;cursor:default;transition:background .12s}
.legend li:hover,.legend li:focus-visible{background:#f2efe6;outline:none}
.legend li:focus-visible{box-shadow:0 0 0 2px rgba(138,43,31,.35)}
polygon[data-series]{transition:opacity .12s,stroke-width .12s}
svg.radar.isolating polygon[data-series]{opacity:.10}
svg.radar.isolating polygon[data-series].hot{opacity:1;stroke-width:3.5}
.swatch-line{flex:0 0 auto;display:block}
.lg-name{flex:1;font-family:ui-monospace,Menlo,monospace;font-size:12px}
.lg-score{color:var(--dim);font-variant-numeric:tabular-nums}
.swatch,.chip{display:inline-block;width:10px;height:10px;border-radius:2px;
vertical-align:middle;margin-right:6px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.12)}
table{width:100%;border-collapse:collapse;font-size:13.5px;background:#fff}
th{text-align:left;font-weight:600;color:var(--dim);font-size:11.5px;
text-transform:uppercase;letter-spacing:.05em;padding:7px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid #f0eee7;vertical-align:middle}
.num{text-align:right;font-variant-numeric:tabular-nums}
.strong{font-weight:700}
.board{margin-top:8px;border:1px solid var(--line)}
th button.sort{font:inherit;color:inherit;text-transform:inherit;letter-spacing:inherit;
background:none;border:0;padding:0;cursor:pointer;text-align:inherit}
th button.sort:hover,th button.sort:focus-visible{color:var(--accent)}
th[aria-sort=ascending] button.sort::after{content:" \\25B2";font-size:9px}
th[aria-sort=descending] button.sort::after{content:" \\25BC";font-size:9px}
.pill{display:inline-block;padding:1px 6px;border-radius:999px;font-size:11px;
font-weight:600;letter-spacing:.03em}
.pill.ok{background:#e7f2e9;color:var(--ok)}
.pill.mid{background:#f6f0d8;color:var(--mid)}
.pill.bad{background:#fbe8e5;color:var(--bad)}
.flag{font-size:11px;color:var(--dim);margin-left:4px}
.ref{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
border:1px solid var(--line);border-radius:3px;padding:0 4px}
.cards{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px;margin-top:14px}
@media(max-width:980px){.cards{grid-template-columns:1fr}}
.card{background:#fff;border:1px solid var(--line);padding:16px 16px 18px}
.card h3{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:ui-monospace,Menlo,monospace;font-size:14px}
.scorebadge{margin-left:auto;background:var(--ink);color:#fff;font-size:11.5px;
padding:1px 7px;border-radius:999px;font-family:-apple-system,sans-serif}
.meta{font-size:12px;color:var(--dim);margin:0 0 8px}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(138,43,31,.35)}
a:hover{border-bottom-color:var(--accent)}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.repolink{white-space:nowrap;font-size:11.5px;color:var(--dim);
border-bottom:1px solid rgba(107,107,107,.35);margin-left:2px}
.scheme-list li{font-size:13.5px}
.scheme-list b{font-weight:600}
.intent{font-size:13px;margin:0 0 10px}
.axescore{list-style:none;display:flex;flex-wrap:wrap;gap:4px 14px;padding:0;margin:0 0 12px;
font-size:11.5px;color:var(--dim)}
.axescore b{color:var(--ink);font-variant-numeric:tabular-nums}
.repair{margin-top:14px;padding-top:4px;border-top:1px solid var(--line)}
.repairs{list-style:none;padding:0;margin:0 0 8px;font-size:12px}
.repairs li{padding:2px 0;border-bottom:1px dotted #efede6}
.dimtxt{color:var(--dim)}
.delta{font-variant-numeric:tabular-nums;font-size:11px;margin-left:3px}
.delta.good{color:var(--ok)}.delta.mid{color:var(--mid)}.delta.bad{color:var(--bad)}
.delta.up{color:var(--ok)}.delta.down{color:var(--bad)}
.method{font-size:13.5px;color:#333}
.term-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:14px 0 6px}
.subhead{margin:26px 0 2px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
figure.term{margin:0;background:#fff;border:1px solid var(--line);padding:10px 10px 8px}
figure.term figcaption{font-size:11.5px;color:var(--dim);margin-bottom:8px;
display:flex;flex-wrap:wrap;gap:3px 8px;align-items:baseline}
figure.term figcaption code{font-size:12px;color:var(--ink)}
.riskchip{font-size:10px;border:1px solid #e6d2cb;background:#fdf3f0;color:var(--bad);
border-radius:999px;padding:0 6px;white-space:nowrap}
.screen{border-radius:6px;padding:11px 12px 9px;
font:11.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
-webkit-print-color-adjust:exact;print-color-adjust:exact}
.screen .ln{white-space:pre;overflow:hidden;text-overflow:ellipsis}
.swatches{display:flex;gap:2px;margin-top:11px}
.swatches i{flex:1;height:11px;border-radius:2px}
.swatches i.derived{opacity:.5}
.hl{color:var(--ink);font-weight:600}
.method li{margin-bottom:6px}
@media print{
 @page{margin:12mm}
 body{background:white;color:black;font-size:10pt}
 .wrap{max-width:none;padding:0}
 .grid,.cards,.term-grid{display:block}
 figure.term{break-inside:avoid;margin-bottom:8pt}
 .screen{border:1px solid #bbb}
 .chart,.card,.verdict{background:none;border-color:#777;margin-bottom:12pt}
 table,thead,tbody,tr,th,td,.references,.pill,.scorebadge{background:none!important;color:black!important}
 th,td{border-color:#aaa}
 .pill{border:1px solid #777}
 .table-scroll{overflow:visible}
 .board{font-size:8pt}
 .board code{font-size:7pt}
 .radar{max-width:115mm;margin:auto}
 .radar polygon{fill:none}
 svg.radar.isolating polygon[data-series]{opacity:1}
 .legend li:hover{background:none}
 .chart{break-inside:avoid}
 tr{break-inside:avoid}
 thead{display:table-header-group}
 h2,h3,h4{break-after:avoid}
 .scorebadge{border:1px solid #777}
}
footer{margin-top:50px;padding-top:14px;border-top:1px solid var(--line);
font-size:12px;color:var(--dim)}
"""


def build(out_path):
    allp = [analyse(k, p) for k, p in PALETTES.items()]
    # Tables are ordered by the long-session score: that is the question this
    # report is for. The contrast-first score and rank ride along so the reorder
    # is visible rather than silent.
    light = sorted([s for s in allp if s['mode'] == 'light'],
                   key=lambda s: (not s['contender'], -s['scores']['session']))
    dark = sorted([s for s in allp if s['mode'] == 'dark'],
                  key=lambda s: (not s['contender'], -s['scores']['session']))

    def board_rows(rows):
        cont = [s for s in rows if s['contender']]
        refs = [s for s in rows if not s['contender']]
        return cont + refs

    # Everything ranked, including derived variants (they belong in the tables).
    light_ranked = [s for s in light if s['contender']]
    dark_ranked = [s for s in dark if s['contender']]
    # The radar compares independent palettes. A derived variant has the same
    # shape as its source by construction, so plotting both doubles the ink for
    # no information; the leaderboard and cards carry the delta instead.
    light_series = [s for s in light_ranked if not s.get('variant')]
    dark_series = [s for s in dark_ranked if not s.get('variant')]
    # Things the radar deliberately does not draw, named rather than implied.
    ref_names = [s['key'] for s in light + dark if not s['contender']]
    ref_note = ''
    if ref_names:
        ref_note = (' Reference palettes (%s) are audited UI systems rather than syntax '
                    'themes, so they stay unranked and unplotted: their scores appear in '
                    'the leaderboards, but their shapes would set the scale\'s extremes '
                    'instead of being compared.' % ', '.join(ref_names))

    lb_light = leaderboard(board_rows(light), 'Light mode leaderboard',
                           'Positive polarity, ranked by long-session score. The contrast-first '
                           'column shows the other view and the delta between them; rows below the '
                           'divider are reference-only and not ranked.')
    lb_dark = leaderboard(board_rows(dark), 'Dark mode leaderboard',
                          'Negative polarity, ranked by long-session score. The contrast-first '
                          'column shows the other view and the delta between them; rows below the '
                          'divider are reference-only and not ranked.')

    def best(rows, profile):
        return max(rows, key=lambda s: s['scores'][profile])

    best_session_light, best_contrast_light = best(light_ranked, 'session'), best(light_ranked, 'contrast')
    best_session_dark, best_contrast_dark = best(dark_ranked, 'session'), best(dark_ranked, 'contrast')
    best_light, best_dark = best_session_light, best_session_dark
    flexoki_dark = next(s for s in dark_series if s['key'] == 'flexoki-dark')
    colour_leader = max(light_ranked + dark_ranked, key=lambda s: s['axes']['color'])
    tightest_dark = min(dark_ranked, key=lambda s: s['span'])
    same_light = best_session_light['key'] == best_contrast_light['key']
    same_dark = best_session_dark['key'] == best_contrast_dark['key']
    if same_light and same_dark:
        agreement_note = ('Both weightings pick the same two winners, so the winner is not an '
                          'artefact of the weights.')
    else:
        agreement_note = ('The weightings disagree, which is the point of showing both: '
                          'contrast-first picks %s in light and %s in dark.'
                          % (best_contrast_light['key'], best_contrast_dark['key']))
    mover = max(light_ranked + dark_ranked,
                key=lambda s: abs(s['scores']['session'] - s['scores']['contrast']))
    mover_delta = mover['scores']['session'] - mover['scores']['contrast']
    biggest_mover_note = ('The biggest reorder is %s, %+.1f (%.1f long-session vs %.1f '
                          'contrast-first).' % (mover['key'], mover_delta,
                                                mover['scores']['session'],
                                                mover['scores']['contrast']))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Palette evaluation: terminal/CLI themes</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style></head><body><div class="wrap">

<h1>Palette evaluation for agent CLIs</h1>
<p class="sub">Measured WCAG 2.1 + APCA 0.1.9 across {len(PALETTES)} palettes,
canonical upstream hexes, generated by <code>scripts/palette-report.py</code>.</p>

<div class="verdict">
<p><strong>Long-session view (the question): light &rarr; {best_session_light['key']}
({best_session_light['scores']['session']:.1f}), dark &rarr; {best_session_dark['key']}
({best_session_dark['scores']['session']:.1f}).</strong>
{agreement_note}</p>
<p><strong>What the weighting changes is the order behind them.</strong>
{biggest_mover_note} Colour is worth .20 here and .00 in the compliance view, so the
most colourful palette measured &mdash; {colour_leader['key']} at
{colour_leader['axes']['color']:.0f}/100 &mdash; climbs, and still cannot reach the top
because contrast carries .55 of the weight on its own.</p>
<p><strong>The dark winner trades bloom for contrast, and that is a real cost.</strong>
{best_session_dark['key']} holds {best_session_dark['body']['ratio']:.2f}:1 body text and
{min(r['ratio'] for r in best_session_dark['accents']):.2f}:1 at its weakest accent, but its
peak-foreground span is {best_session_dark['span']:.4f} &mdash; the widest among dark
contenders. {tightest_dark['key']} is the bloom pick at {tightest_dark['span']:.4f} span and
would win if you weight halation hard. {best_session_light['key']} needs
{'no repair at all' if not best_session_light['repairs'] else '%.1f ΔL of repair' % best_session_light['max_repair']};
{best_session_dark['key']}
{'needs none either' if not best_session_dark['repairs'] else 'needs %.1f ΔL' % best_session_dark['max_repair']}.</p>
<p class="note">Eye strain is not a property of a palette. Contrast and brightness are proxies for
less decoding effort; colour is a preference plus a syntax-separation aid, not a strain lever.
The fatigue literature found no significant polarity effect; polarity is set by the room.</p>
</div>

<h2>Leaderboard</h2>
<p class="note">Two weightings, one set of measurements. <b>Long-session</b> is the ranking used
below: body .15, dim .15, worst accent .15, accent coverage .10, colour .20, comfort .15,
repair .10. <b>Contrast-first</b> is the earlier compliance view: body .20, dim .20, worst
accent .20, coverage .15, comfort .10, repair .15, colour .00. The delta column is
long-session minus contrast-first, so a positive number means the palette gains when colour
and comfort are counted.</p>
<p class="note">Two standards gate every accent term. <code>worst accent</code> and
<code>accents ≥4.5:1</code> are WCAG 2.1; <code>accents Lc≥60</code> and <code>worst Lc</code>
are APCA 0.1.9, where 60 is the content-text floor. An accent counts toward coverage only
when it clears both, and the worst-accent axis takes the weaker of the two scaled to its own
pass mark &mdash; a 12:1 accent that blooms cannot saturate it. The two standards agree in
light mode on this set; they part company in dark mode, where APCA demotes the soft palettes
that WCAG passes.</p>
{lb_light}
{lb_dark}

<h2>Spider graph</h2>
<p class="note">Seven axes, each 0&ndash;100 and higher-is-better, computed from the tables below:
body-text ratio, dim-text contrast, worst accent, share of accents clearing <b>both</b>
gates (WCAG 4.5:1 and APCA Lc 60),
<b>colour</b> (mean Oklab chroma plus worst accent-pair &Delta;E), comfort headroom against the
mode's failure mode (glare in light, halation in dark), and repairability (identity cost).
The same seven values feed both weightings; only the weights differ, so the shape is the
evidence and the score is a reading of it. Hover or tab a legend row to fade every
other series. Derived variants marked <span class="ref">shipped</span> are not plotted:
their shape equals their source by construction, so the leaderboard carries their delta
instead. A palette can lose on the mean and still be the right pick for a mood.{ref_note}</p>
<div class="grid">
<div class="chart">{radar('light', light_series)}<h4>Light mode</h4>{legend(light_series)}</div>
<div class="chart">{radar('dark', dark_series)}<h4>Dark mode</h4>{legend(dark_series)}</div>
</div>

<h2>Terminal preview</h2>
<p class="note">Each pane renders the palette's own colours on its own background over a mock
agent-CLI transcript: prompt, search result, a diff pair, a warning, an error and an agent label.
The eight canonical ANSI roles are the palette's published accents &mdash; magenta falls back to
purple/mauve, cyan to aqua/teal, black to the dim colour, white to body text. The faded second row
is a <b>derived</b> bright variant (same hue and saturation, lightness moved 10% away from the
background), because these projects publish 6&ndash;9 accents rather than a 16-colour ANSI table:
set your terminal from the canonical values and treat the brights as illustrative.
<span class="hl">Bloom and glare are not simulated.</span> Halation depends on your room, your
pupil and your display luminance; a screenshot cannot reproduce it. Read the span column instead.</p>
<div class="term-grid">
{''.join(terminal_preview(s) for s in light)}
</div>
<h3 class="subhead">Dark mode</h3>
<div class="term-grid">
{''.join(terminal_preview(s) for s in dark)}
</div>

<h2>Details by palette</h2>
<div class="cards">
{''.join(palette_card(s) for s in light)}
</div>
<div class="cards">
{''.join(palette_card(s) for s in dark)}
</div>

<h2>Guarantee check: Radix Colors</h2>
<p class="note">Radix documents targets of |Lc| 60 for step 11 and |Lc| 90 for step 12
against step 2. The table computes APCA 0.1.9 from embedded opaque
<code>@radix-ui/colors</code> CSS hexes; it tests the claim under this report's formula.</p>
{radix_table()}
<p class="note">In these sampled scales, step 11 clears |Lc| 60 in both modes.
Step 12 clears |Lc| 90 in light mode; dark blue and tomato miss that target under
APCA 0.1.9. Dark gray passes but crosses the halation signal. These samples do not
establish a guarantee for every Radix scale or APCA version.</p>

<h2>Scheme sources</h2>
<p class="note">Every hex in this report was read from these pages, not from a local port.
Links open in a new tab.</p>
<ul class="method scheme-list">
{scheme_links()}
</ul>

<h2>Method, and what this does not measure</h2>
<ul class="method">
<li><b>WCAG 2.1</b> relative luminance, ratio <code>(L1+.05)/(L2+.05)</code>. Polarity-blind:
white-on-black and black-on-white score identically, so it cannot see halation.</li>
<li><b>APCA 0.1.9</b> (W3C silver draft constants). Polarity-aware, signed: negative Lc means
light text on dark. Content floor <code>|Lc|&nbsp;&ge;&nbsp;60</code>, body floor 75, and
<code>|Lc|&nbsp;&gt;&nbsp;95</code> in dark mode is the halation ceiling, not a win.
APCA 0.2.x uses different exponents &mdash; these numbers are version-specific.</li>
<li><b>Colour</b> is two things measured in Oklab: mean chroma across accents (hedonic
&mdash; how colourful it looks), and the worst pairwise Oklab distance between two accents
(functional &mdash; whether a string and a keyword remain distinguishable). Chroma maps
0.08&ndash;0.20 to 0&ndash;100 and separability maps 0.04&ndash;0.06 to 0&ndash;100, then
0.6/0.4. Those bands are observed ranges over these twelve palettes, not perceptual
thresholds: the axis ranks the set, it does not certify a palette.</li>
<li><b>Repair cost</b> holds hue and saturation constant and moves lightness until the pair
clears 4.5:1, in 0.004 HLS lightness steps toward the far pole. Cost is ΔL × 100,
in lightness percentage points, not a percentage change or a perceptual distance.
Only failing accents enter the repair table; body and dim failures remain visible above.</li>
<li><b>Peak-foreground span</b> is <code>max(relLum) &minus; relLum(bg)</code> over body, dim
and accent roles. The peak can be an accent, but body brightness is the primary sustained halation lever.
Light-mode spans are negative by construction, so those leaderboards show surface
relative luminance instead.</li>
<li><b>Composite and radar:</b> body = min(100, ratio / 21 × 100);
light dim = min(100, ratio / 7 × 100); dark dim = min(100, |Lc| / 75 × 100);
worst accent = min(min(100, ratio / 4.5 × 100), min(100, |Lc| / 60 × 100));
accent coverage = accents clearing <em>both</em> gates / total × 100.
Light comfort = clamp((1 − surface relLum) / 0.12 × 100, 0, 100);
dark comfort = clamp((1 − peak span / 0.90) × 100, 0, 100).
Repairability = max(0, 100 − max repair / 25 × 100). These are declared scoring
heuristics, not validated comfort scales; a high score does not override a dark-mode
|Lc| &gt; 95 warning. Scores compare palettes within a mode.</li>
<li><b>Precision and bands:</b> ratios use four decimals and signed Lc uses two;
thresholds use unrounded values. AAA ≥ 7, AA ≥ 4.5, FAIL &lt; 4.5 apply the WCAG
normal-text thresholds. APCA floors here are screening heuristics; font size and weight
still matter. Role hexes are embedded snapshots, not measurements of installed ports.</li>
<li><b>Two standards, not one:</b> WCAG 2.1 is polarity-symmetric and saturates at 4.5:1,
so it can see neither halation above the dark ceiling nor how far a saturated accent falls
below APCA's content floor. APCA 0.1.9 models polarity but is a draft, its thresholds are
guidance rather than a standard, and it weights luminance only &mdash; a vivid accent can pass
WCAG and sit at Lc 40. Rather than average the two (which would invent weights) each accent
term takes the weaker standard, so a palette has to satisfy both to score well, and the
tables show both counts so the disagreement stays visible.</li>
<li><b>Not measured:</b> font size and weight, room brightness, monitor luminance, blink
rate, astigmatism, or how long you actually look away. These limit what this comparison can predict. The cited polarity studies favor
positive polarity for decoding tasks, especially small text at night; that does not
establish that a palette reduces eye strain.</li>
</ul>

<h2>Sources</h2>
<ul class="method">
<li>Measurement definitions: WCAG 2.1, relative luminance and contrast ratio
(W3C Recommendation); APCA 0.1.9 silver-draft constants, embedded in this generator.</li>
<li>Palette inputs: protesilaos.com/emacs/modus-themes-colors;
stephango.com/flexoki; morhetz/gruvbox Xresources; catppuccin/palette;
sainnhe/everforest palette.md; primer/primitives syntax.json5 ANSI block.
Radix inputs and contrast targets: @radix-ui/colors CSS and
radix-ui.com/colors/docs/palette-composition/understanding-the-scale.
Upstream intent is attributed in each card, separate from computed results.</li>
<li>Buchner &amp; Baumgartner (2007), <i>Ergonomics</i> 50(7):1036&ndash;63 &mdash; positive
polarity advantage, independent of ambient light; colour contrast cannot substitute for
luminance contrast.</li>
<li>Piepenbrock et al. (2013, 2014) &mdash; acuity and proofreading better in positive
polarity across ages; advantage grows as font size shrinks; <b>no significant fatigue
difference</b> by polarity.</li>
<li>Dobres, Chahine &amp; Reimer (2017), <i>Applied Ergonomics</i> &mdash; no polarity effect
in daylight; light mode wins at night; small text worst in dark mode.</li>
<li>2022, "Dark mode vogue" (PMID 36533999) &mdash; negative polarity raises cognitive load
and search time.</li>
<li>2023 (PMC11175232) &mdash; under negative polarity, fatigue by text colour ranks
red &gt; green &gt; blue &gt; white &gt; yellow.</li>
<li>Sarkar (2015) PPIG &mdash; syntax colouring cut completion time 8.4&nbsp;s and context
switches; Hanenberg et al. (2018, 390 subjects) found no comprehension benefit. Contested.</li>
</ul>

<footer>Generated by <code>scripts/palette-report.py</code>. Hexes are canonical upstream
values, not local ports &mdash; ports drift. Re-run after any palette change.</footer>
</div><script>{ISOLATE_JS}{SORT_JS}</script></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
    return allp, out_path


def text_report(allp):
    for mode in ('light', 'dark'):
        rows = sorted([s for s in allp if s['mode'] == mode],
                      key=lambda s: (not s['contender'], -s['scores']['session']))
        print('\n== %s ==' % mode)
        print('%-22s %7s %8s %6s %6s %6s %7s %5s %5s %7s %6s' % (
            'palette', 'session', 'contrast', 'body', 'dim', 'worst',
            'wcag/apca', 'colr', 'span' if mode == 'dark' else 'surface', 'uni', 'repair'))
        for s in rows:
            print('%-22s %7.1f %8.1f %6.2f %6.2f %6.2f %3d/%-2d %2d/%-2d %5.0f %7.3f %6s' % (
                s['key'] + ('' if s['contender'] else ' (ref)'),
                s['scores']['session'], s['scores']['contrast'],
                s['body']['ratio'], s['dim']['ratio'],
                min(x['ratio'] for x in s['accents']),
                len(s['accents']) - len(s['fails']), len(s['accents']),
                len(s['pass_both']), len(s['accents']),
                s['axes']['color'],
                s['span'] if mode == 'dark' else rel_lum(hex2rgb(s['bg'])),
                '%.1f' % s['max_repair']))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(pathlib.Path(__file__).resolve().parent.parent
                                         / 'docs' / 'palette-report.html'))
    ap.add_argument('--text', action='store_true')
    args = ap.parse_args()
    if args.text:
        text_report([analyse(k, p) for k, p in PALETTES.items()])
    else:
        allp, path = build(pathlib.Path(args.out))
        text_report(allp)
        print('\nwrote %s' % path)
