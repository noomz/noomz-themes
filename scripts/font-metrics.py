#!/usr/bin/env python3
"""Measure monospace fonts for the long-session legibility report.

Pure measurement. No scoring here — see font-report.py for the heuristic
weightings that turn these numbers into a ranking.

Everything is derived from the font binaries on this machine: glyph outlines
via fontTools, and FreeType rasterisation via Pillow at a fixed pixel size.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont, TTCollection

# System fonts carry table quirks that fontTools warns about on every open. The
# inventory opens a thousand files, so the warnings are noise here.
logging.getLogger("fontTools").setLevel(logging.ERROR)

FC_LIST = "/opt/homebrew/bin/fc-list"

# Where fonts live on this machine. The inventory walks these directories rather
# than asking fontconfig for spacing=100: fontconfig reports Monaco's spacing as
# dual, so a fontconfig-only inventory silently drops fonts a terminal chooser
# still offers. Membership is decided by measuring the font, not by asking a
# database about it.
FONT_DIRS = [
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    "/opt/homebrew/share/fonts",
    "/usr/local/share/fonts",
]
FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")
# A face counts as monospaced when its printable ASCII advances are all equal.
# 90 of the 95 characters is the floor; a few faces legitimately omit a glyph.
ASCII_RANGE = range(0x20, 0x7F)
ASCII_FLOOR = 90

# Rasterisation size for shape measurements. Big enough that a 1px quantisation
# error is <2% of a stem, and it is the same for every font.
SHAPE_PX = 192

# Text size for ink-density measurement. Terminal body text lives near here.
INK_PX = 13

# Pairs that carry meaning in code and that readers confuse.
CONFUSABLE_PAIRS = [
    ("0", "O"), ("0", "o"), ("O", "o"), ("8", "B"), ("8", "&"),
    ("1", "l"), ("1", "I"), ("l", "I"), ("1", "|"), ("l", "|"),
    ("5", "S"), ("5", "s"), ("2", "Z"), ("2", "z"), ("6", "b"),
    ("9", "g"), ("9", "q"), ("g", "q"), ("p", "q"), ("f", "t"),
    (";", ":"), ("i", "j"), ("i", "l"), (".", ","), ("u", "v"),
    ("v", "y"), ("c", "C"), ("x", "x"), ("w", "W"), ("0", "8"),
]
CONFUSABLE_MULTI = [("rn", "m"), ("cl", "d"), ("vv", "w"), ("ii", "u")]


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

@dataclass
class Face:
    path: str
    index: int
    family: str
    subfamily: str
    full_name: str
    typographic_family: str
    is_mono: bool
    is_bold: bool
    is_italic: bool
    weight_class: int
    is_variable: bool
    file_kind: str

    @property
    def key(self) -> str:
        return f"{self.path}#{self.index}"


def _name(font: TTFont, name_id: int) -> str:
    for record in font["name"].names:
        if record.nameID == name_id:
            try:
                value = record.toUnicode()
            except Exception:
                continue
            if value.strip():
                return value.strip()
    return ""


def _is_monospaced(font: TTFont) -> bool:
    """Do all printable ASCII advances agree? The cheap, decisive test."""
    try:
        cmap = font.getBestCmap()
        hmtx = font["hmtx"].metrics
    except Exception:
        return False
    widths = {hmtx[cmap[code]][0] for code in ASCII_RANGE if code in cmap}
    present = sum(1 for code in ASCII_RANGE if code in cmap)
    return present >= ASCII_FLOOR and len(widths) == 1


def _candidate_paths(extra_dirs: list[str]) -> list[str]:
    """Font files from the standard directories, plus anything fontconfig knows."""
    paths: set[str] = set()
    for directory in FONT_DIRS + extra_dirs:
        for root, _dirs, files in os.walk(directory):
            for name in files:
                if name.lower().endswith(FONT_EXTENSIONS):
                    paths.add(os.path.join(root, name))
    try:
        raw = subprocess.run([FC_LIST, "file"], capture_output=True, text=True,
                             check=True).stdout
        for line in raw.splitlines():
            candidate = line.split(":", 1)[0].strip()
            if candidate.lower().endswith(FONT_EXTENSIONS) and os.path.exists(candidate):
                paths.add(candidate)
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(paths)


def load_faces(extra_dirs: list[str]) -> tuple[list[Face], dict[str, int]]:
    """Every monospaced face on the machine, with TTC members expanded.

    A collection is tested member by member, because a .ttc can mix a monospaced
    face with proportional ones alongside it.
    """
    faces: list[Face] = []
    stats = {"files": 0, "unreadable": 0, "proportional_faces": 0, "monospaced_faces": 0}
    skipped: set[str] = set()
    for path in _candidate_paths(extra_dirs):
        stats["files"] += 1
        try:
            if path.lower().endswith((".ttc", ".otc")):
                collection = TTCollection(path, lazy=True)
                for index, font in enumerate(collection.fonts):
                    if _is_monospaced(font):
                        faces.append(_face_from_font(font, path, index, "ttc"))
                        stats["monospaced_faces"] += 1
                    else:
                        stats["proportional_faces"] += 1
                        skipped.add(font.get("name") and _name(font, 1) or os.path.basename(path))
            else:
                font = TTFont(path, lazy=True, fontNumber=0)
                if _is_monospaced(font):
                    kind = "cff" if "CFF " in font or "CFF2" in font else "glyf"
                    faces.append(_face_from_font(font, path, 0, kind))
                    stats["monospaced_faces"] += 1
                else:
                    stats["proportional_faces"] += 1
                    skipped.add(_name(font, 1) or os.path.basename(path))
                font.close()
        except Exception:
            stats["unreadable"] += 1
            continue
    stats["skipped_families"] = sorted(name for name in skipped if name)
    return faces, stats


def _face_from_font(font: TTFont, path: str, index: int, kind: str) -> Face:
    os2 = font.get("OS/2")
    flags = os2.fsSelection if os2 else 0
    mac_style = font["head"].macStyle if "head" in font else 0
    is_bold = bool(mac_style & 0b1) or bool(flags & 0b100000)
    # Some fonts leave the style bits unset on slanted faces, SF Mono among them, so a
    # nonzero post.italicAngle counts too.
    is_italic = (bool(mac_style & 0b10) or bool(flags & 0b1) or bool(flags & 0b1000000000)
                 or bool(font["post"].italicAngle if "post" in font else 0))
    family = _name(font, 16) or _name(font, 1) or os.path.basename(path)
    subfamily = _name(font, 17) or _name(font, 2) or ""
    full = _name(font, 4) or family
    return Face(
        path=path,
        index=index,
        family=family,
        subfamily=subfamily,
        full_name=full,
        typographic_family=family,
        is_mono=True,
        is_bold=is_bold,
        is_italic=is_italic,
        weight_class=os2.usWeightClass if os2 else 400,
        is_variable="fvar" in font,
        file_kind=kind,
    )


# --------------------------------------------------------------------------
# rasterisation helpers
# --------------------------------------------------------------------------

def _font(path: str, index: int, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, px, index=index)


def glyph_mask(font: ImageFont.FreeTypeFont, text: str) -> tuple[Image.Image, int, int]:
    """Tight ink mask of `text`, plus the (dx, dy) offsets from the pen origin."""
    bbox = font.getbbox(text)
    if bbox is None:
        return Image.new("L", (1, 1), 0), 0, 0
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.text((-left, -top), text, font=font, fill=255)
    return image, left, -top


def ink_ratio(mask: Image.Image) -> float:
    data = mask.tobytes()
    return sum(1 for value in data if value > 127) / max(1, len(data))


def runs_in_row(mask: Image.Image, row: int, threshold: int = 127) -> list[int]:
    width = mask.width
    data = mask.crop((0, row, width, row + 1)).tobytes()
    runs: list[int] = []
    current = 0
    for value in data:
        if value > threshold:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def runs_in_col(mask: Image.Image, col: int, threshold: int = 127) -> list[int]:
    height = mask.height
    data = mask.crop((col, 0, col + 1, height)).tobytes()
    runs: list[int] = []
    current = 0
    for value in data:
        if value > threshold:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def stroke_contrast(path: str, index: int) -> dict[str, Any] | None:
    """Thickest and thinnest horizontal/vertical stroke of a round letter.

    'o' has horizontal stress in every text face worth measuring, so its left and
    right walls are the thick strokes and its top and bottom are the thin ones.
    Reported as a ratio: 1.00 is a monolinear face.
    """
    font = _font(path, index, SHAPE_PX)
    mask, left, _top = glyph_mask(font, "o")
    if mask.width < 8 or mask.height < 8:
        mask, left, _top = glyph_mask(font, "e")
        if mask.width < 8 or mask.height < 8:
            return None
    mid_row = mask.height // 2
    mid_col = mask.width // 2
    row_runs = runs_in_row(mask, mid_row)
    col_runs = runs_in_col(mask, mid_col)
    if len(row_runs) < 2 or len(col_runs) < 2:
        return None
    thick = (row_runs[0] + row_runs[-1]) / 2
    thin = (col_runs[0] + col_runs[-1]) / 2
    if thin <= 0:
        return None
    ratio = thick / thin
    return {
        "thick_px": round(thick, 2),
        "thin_px": round(thin, 2),
        "contrast": round(ratio, 3),
        # stem as a fraction of the em box, comparable across fonts
        "stem_em": round(thick / SHAPE_PX, 4),
    }


def glyph_distance(path_a: str, index_a: int, path_b: str, index_b: int,
                   text_a: str, text_b: str, px: int = SHAPE_PX) -> float | None:
    """Symmetric difference of two glyph masks over their union.

    0.0 means the two render identically (maximally confusable), 1.0 means they
    share no ink. Masks are aligned on the pen origin, so advance and side
    bearing differences count as difference — which is what a reader sees.
    """
    fa = _font(path_a, index_a, px)
    fb = _font(path_b, index_b, px)
    ma, ax, ay = glyph_mask(fa, text_a)
    mb, bx, by = glyph_mask(fb, text_b)
    pad = 4
    min_x = min(ax, bx) - pad
    min_y = min(ay, by) - pad
    width = max(ax + ma.width, bx + mb.width) - min_x + pad
    height = max(ay + ma.height, by + mb.height) - min_y + pad
    canvas_a = Image.new("L", (width, height), 0)
    canvas_b = Image.new("L", (width, height), 0)
    canvas_a.paste(ma, (ax - min_x, ay - min_y))
    canvas_b.paste(mb, (bx - min_x, by - min_y))
    da = canvas_a.tobytes()
    db = canvas_b.tobytes()
    union = 0
    diff = 0
    for pa, pb in zip(da, db):
        ia = pa > 127
        ib = pb > 127
        if ia or ib:
            union += 1
            if ia != ib:
                diff += 1
    if union == 0:
        return None
    return diff / union


def _mark_slope(inner: Image.Image) -> float | None:
    """Least-squares slope of the mark's horizontal centre as it descends.

    A slash walks across the counter as it falls, so its row centroids drift; a
    dot is a compact blob and its centroids stay put. Slope is in pixels of
    drift per pixel of descent. Hack's zero holds a tall thin dot and Menlo's
    holds a short slash, so neither aspect ratio nor ink area separates them —
    this does.
    """
    pixels = inner.load()
    rows: list[tuple[float, float]] = []
    for y in range(inner.height):
        xs = [x for x in range(inner.width) if pixels[x, y] > 127]
        if xs:
            rows.append((float(y), sum(xs) / len(xs)))
    if len(rows) < 3:
        return None
    mean_y = sum(y for y, _x in rows) / len(rows)
    mean_x = sum(x for _y, x in rows) / len(rows)
    numerator = sum((y - mean_y) * (x - mean_x) for y, x in rows)
    denominator = sum((y - mean_y) ** 2 for y, _x in rows)
    if denominator == 0:
        return None
    return numerator / denominator


def zero_style(path: str, index: int) -> dict[str, Any]:
    """Dotted, slashed, or plain zero, plus the ink fraction inside the counter."""
    px = SHAPE_PX
    font = _font(path, index, px)
    mask, _left, _top = glyph_mask(font, "0")
    if mask.width < 10 or mask.height < 10:
        return {"style": "unknown", "counter_ink": None, "mark_slope": None}
    advance = font.getlength("0")
    # the counter: the middle of the glyph, where the mark can be drawn
    inner = mask.crop((int(mask.width * 0.30), int(mask.height * 0.30),
                       max(int(mask.width * 0.70), 1) + 1,
                       max(int(mask.height * 0.70), 1) + 1))
    ratio = ink_ratio(inner)
    slope = _mark_slope(inner)
    if ratio < 0.02 or slope is None:
        style = "plain"
    else:
        style = "slashed" if abs(slope) > 0.30 else "dotted"
    return {
        "style": style,
        "counter_ink": round(ratio, 4),
        "mark_slope": round(slope, 3) if slope is not None else None,
        "advance_px": round(advance, 3),
    }


def cell_continuity(path: str, index: int) -> dict[str, Any]:
    """Does a rule glyph reach the cell edges? Terminals and TUIs depend on it.

    Measured by projection, not by guessing a row or column: a two-cell rule is
    continuous when its ink starts within a pixel of the left cell edge, ends
    within a pixel of the right cell edge, and has no interior gap. The same
    shape of test runs vertically for the vertical rules.
    """
    font = _font(path, index, SHAPE_PX)
    advance = font.getlength("M")
    result: dict[str, Any] = {"advance_px": round(advance, 3)}

    def continuity(ch: str, axis: str) -> dict[str, Any] | None:
        double = ch + ch
        mask, _left, _top = glyph_mask(font, double)
        if mask.width < 4 or mask.height < 4:
            return None
        if axis == "h":
            present = [any(pixel > 127 for pixel in mask.crop((x, 0, x + 1, mask.height)).tobytes())
                       for x in range(mask.width)]
            span = 2 * advance
        else:
            present = [any(pixel > 127 for pixel in mask.crop((0, y, mask.width, y + 1)).tobytes())
                       for y in range(mask.height)]
            span = mask.height
        first = present.index(True) if any(present) else None
        last = len(present) - 1 - present[::-1].index(True) if any(present) else None
        if first is None or last is None:
            return None
        gap = max((len(part) for part in "".join("1" if p else "0" for p in present[first:last + 1]).split("1")), default=0)
        return {
            "reach_start": round(first, 2),
            "reach_end": round(last - span + 1, 2),
            "coverage": round((last - first + 1) / span, 3),
            "max_gap_px": gap,
            "continuous": bool(first <= 1 and (span - 1 - last) <= 1 and gap <= 1),
        }

    for label, ch, axis in (("box_h", "\u2500", "h"), ("box_v", "\u2502", "v"),
                            ("underscore", "_", "h"), ("overline", "\u203e", "h"),
                            ("block_full", "\u2588", "h")):
        try:
            result[label] = continuity(ch, axis)
        except Exception:
            result[label] = None
    # powerline separator: ink width and advance against the cell it occupies
    try:
        pua = "\ue0b0"
        pua_advance = font.getlength(pua)
        pl, _pl_left, _pl_top = glyph_mask(font, pua)
        result["powerline"] = {
            "ink_w_cells": round(pl.width / advance, 3) if advance else None,
            "ink_h_em": round(pl.height / SHAPE_PX, 3),
            "own_advance_cells": round(pua_advance / advance, 3) if advance else None,
        }
    except Exception:
        result["powerline"] = None
    return result


def ink_density(path: str, index: int) -> dict[str, Any]:
    """Optical density of a screenful of text at body-text size.

    Ink pixels of a specimen divided by the cell area it occupied
    (advance x line height), which is what makes a full screen of code read as
    light or heavy. Too little ink and letterforms go faint at small sizes; too
    much and antialiasing closes the counters.
    """
    font = _font(path, index, INK_PX)
    advance = font.getlength("M")
    line_height = INK_PX * 1.42
    result: dict[str, Any] = {"advance_px": round(advance, 4),
                             "cols_per_1000px": round(1000 / advance, 2) if advance else None,
                             "cell_w_em": round(advance / INK_PX, 4) if advance else None}
    cell_area = advance * line_height * 60
    for label, sample in (("body", "the quick brown fox jumps over 0123456789"),
                          ("code", "if (x != null) { return foo.bar(1); }")):
        mask, _l, _t = glyph_mask(font, sample)
        ink = sum(1 for value in mask.tobytes() if value > 127)
        result[f"ink_{label}"] = round(ink / cell_area, 4)
    return result


def vertical_metrics(path: str, index: int) -> dict[str, Any]:
    font = TTFont(path, lazy=True, fontNumber=index) if path.lower().endswith(".ttc") \
        else TTFont(path, lazy=True, fontNumber=0)
    upem = font["head"].unitsPerEm
    os2 = font.get("OS/2")
    hhea = font["hhea"]
    out: dict[str, Any] = {
        "upem": upem,
        "typo_ascender": getattr(os2, "sTypoAscender", None),
        "typo_descender": getattr(os2, "sTypoDescender", None),
        "typo_line_gap": getattr(os2, "sTypoLineGap", None),
        "hhea_ascender": hhea.ascender,
        "hhea_descender": hhea.descender,
        "hhea_line_gap": hhea.lineGap,
        "win_ascent": getattr(os2, "usWinAscent", None),
        "win_descent": getattr(os2, "usWinDescent", None),
        "use_typo_metrics": bool(getattr(os2, "fsSelection", 0) & 0b10000000),
        "x_height": getattr(os2, "sxHeight", 0) or None,
        "cap_height": getattr(os2, "sCapHeight", 0) or None,
        "glyph_count": len(font.getGlyphOrder()),
    }
    cmap = font.getBestCmap()
    out["cmap_size"] = len(cmap)
    out["ascii_coverage"] = round(
        sum(1 for code in range(0x20, 0x7F) if code in cmap) / 95, 4)
    # measure x-height and cap-height from outlines when the OS/2 fields are absent
    glyph_set = font.getGlyphSet()
    from fontTools.pens.boundsPen import BoundsPen
    for label, ch in (("x_height", "x"), ("cap_height", "H"), ("asc_height", "b"),
                      ("desc_depth", "p")):
        if out.get(label):
            continue
        name = cmap.get(ord(ch))
        if not name:
            continue
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        if pen.bounds:
            y_min, y_max = pen.bounds[1], pen.bounds[3]
            if label == "desc_depth":
                out[label] = abs(min(0, y_min))
            else:
                out[label] = y_max
    out["default_line_height_em"] = round(
        (hhea.ascender - hhea.descender + hhea.lineGap) / upem, 4)
    out["typo_line_height_em"] = (
        round((out["typo_ascender"] - out["typo_descender"] + (out["typo_line_gap"] or 0)) / upem, 4)
        if out["typo_ascender"] is not None else None)
    for key in ("x_height", "cap_height", "asc_height", "desc_depth"):
        value = out.get(key)
        out[f"{key}_em"] = round(value / upem, 4) if value else None
    # monospace check: max minus min advance over printable ASCII, in units
    widths = {font["hmtx"].metrics[cmap[code]][0]
              for code in range(0x20, 0x7F) if code in cmap}
    out["advance_units"] = min(widths) if widths else None
    out["advance_variance_units"] = (max(widths) - min(widths)) if widths else None
    out["advance_em"] = round((min(widths) / upem) if widths else 0.0, 4)
    out["fixed_pitch_flag"] = bool(getattr(font.get("post"), "isFixedPitch", 0))
    out["italic_angle"] = round(font["post"].italicAngle, 2)
    out["has_instructions"] = _has_instructions(font)
    out["has_gasp"] = "gasp" in font
    out["has_liga"] = _has_feature(font, "liga")
    out["has_calt"] = _has_feature(font, "calt")
    out["is_variable"] = "fvar" in font
    out["axes"] = _axes(font)
    out["features"] = _feature_tags(font)
    out["vendor"] = _name(font, 8)
    out["version"] = _name(font, 5)
    out["license_url"] = [r.toUnicode() for r in font["name"].names
                          if r.nameID == 14][:1]
    font.close()
    return out


def _has_instructions(font: TTFont) -> bool:
    try:
        glyf = font["glyf"]
    except Exception:
        return False
    for name in font.getGlyphOrder()[:4000]:
        try:
            if glyf[name].program:
                return True
        except Exception:
            continue
    return False


def _feature_tags(font: TTFont) -> list[str]:
    try:
        gsub = font["GSUB"].table
        if not gsub.FeatureList:
            return []
        return sorted({record.FeatureTag for record in gsub.FeatureList.FeatureRecord})
    except Exception:
        return []


def _has_feature(font: TTFont, tag: str) -> bool:
    return tag in _feature_tags(font)


def _axes(font: TTFont) -> list[str]:
    try:
        return [axis.axisTag for axis in font["fvar"].axes]
    except Exception:
        return []


def coverage(path: str, index: int) -> dict[str, Any]:
    """Terminal furniture: which of the glyphs a TUI actually draws are present."""
    font = TTFont(path, lazy=True, fontNumber=index if path.lower().endswith(".ttc") else 0)
    cmap = set(font.getBestCmap())
    font.close()
    groups = {
        "box_drawing": list(range(0x2500, 0x2580)),
        "blocks": list(range(0x2580, 0x25A0)),
        "braille": list(range(0x2800, 0x2900)),
        "arrows": list(range(0x2190, 0x2200)),
        "powerline_pua": [0xE0A0, 0xE0A1, 0xE0A2, 0xE0B0, 0xE0B1, 0xE0B2, 0xE0B3],
        "geometric": list(range(0x25A0, 0x2600)),
        "dingbats_checks": [0x2713, 0x2717, 0x2714, 0x2718, 0x26A0, 0x2716],
        "math_ops": [0x2200, 0x2203, 0x2205, 0x2208, 0x2211, 0x221A, 0x2260, 0x2264, 0x2265],
        "greek": list(range(0x3B1, 0x3CA)),
        "cyrillic": list(range(0x410, 0x430)),
        "cjk_smoke": [0x4E00, 0x65E5, 0x672C, 0x8A9E],
        "emoji_smoke": [0x1F600, 0x1F680, 0x2705],
        "nerd_icons": list(range(0xF000, 0xF400)) + list(range(0xE700, 0xE800)),
    }
    out: dict[str, Any] = {}
    for label, codepoints in groups.items():
        present = sum(1 for cp in codepoints if cp in cmap)
        out[label] = present
        out[f"{label}_pct"] = round(present / len(codepoints), 4) if codepoints else None
    return out


def confusability(path: str, index: int) -> dict[str, Any]:
    """Per-pair glyph distinguishability, at design size and at reading size.

    Distance is the symmetric difference of the two ink masks over their union,
    aligned on the pen origin, so a difference in side bearing or advance counts.
    Reported at two sizes because hinting and antialiasing change how similar two
    shapes look once the rasteriser has had them.
    """
    out: dict[str, Any] = {}
    for label, px in (("design", SHAPE_PX), ("render", INK_PX)):
        pairs: dict[str, float] = {}
        for a, b in CONFUSABLE_PAIRS:
            if a == b:
                continue
            distance = glyph_distance(path, index, path, index, a, b, px)
            if distance is not None:
                pairs[f"{a}/{b}"] = round(distance, 4)
        for a, b in CONFUSABLE_MULTI:
            distance = glyph_distance(path, index, path, index, a, b, px)
            if distance is not None:
                pairs[f"{a}/{b}"] = round(distance, 4)
        if not pairs:
            out[label] = None
            continue
        worst_key = min(pairs, key=lambda key: pairs[key])
        out[label] = {
            "worst_pair": worst_key,
            "worst": pairs[worst_key],
            "mean": round(sum(pairs.values()) / len(pairs), 4),
            "under_0_20": sum(1 for value in pairs.values() if value < 0.20),
            "pairs": pairs,
        }
    return out


def design_fingerprint(path: str, index: int) -> str | None:
    """Identity of the design, not of the file.

    Hashes rasterised glyphs rather than outline coordinates. Outlines are the same
    design expressed differently after a rebuild — a Nerd-Font-patched Hack carries
    the same letterforms as Hack with a different point count — so comparing point
    lists reports them as different fonts and comparing pixels does not. The hash
    covers bitmap, ink offsets and advance, so a Mono or Propo variant that changes
    the cell stays separate.
    """
    import hashlib
    digest = hashlib.sha256()
    try:
        font = _font(path, index, 96)
    except Exception:
        return None
    for ch in "aegmRQ0@1lIi5S2Z":
        try:
            mask, left, top = glyph_mask(font, ch)
        except Exception:
            continue
        digest.update(ch.encode())
        digest.update(str(mask.size).encode())
        digest.update(str(font.getlength(ch)).encode())
        # thresholded bits: tolerant of a sub-pixel rendering shift, still sensitive
        # to a different drawing
        digest.update(bytes(1 if value > 127 else 0 for value in mask.tobytes()))
    return digest.hexdigest()[:16]


def _safe(label: str, fn, *args) -> Any:
    try:
        return fn(*args)
    except Exception as error:  # a font that will not rasterise is still a data point
        return {"error": f"{type(error).__name__}: {error}", "stage": label}


def _ink_columns(mask: Image.Image, row: int) -> tuple[int, int] | None:
    data = mask.crop((0, row, mask.width, row + 1)).tobytes()
    xs = [x for x, value in enumerate(data) if value > 127]
    if not xs:
        return None
    return xs[0], xs[-1]


def disambiguation(path: str, index: int) -> dict[str, Any]:
    """The features that tell the classic ambiguous sets apart, measured directly.

    Area-based shape distance under-weights a small but decisive feature, so a
    dotted zero scores as 'similar to O' however well it reads. These are the cues
    themselves: a mark in the zero, a flag and a base on the one, a top arm or a
    foot on the lowercase ell, serifs on the capital eye. A face can be highly
    distinct by silhouette and still carry none of them.

    Flags and arms are found by looking for ink outside the stem's own columns in
    the upper band, which finds a thin diagonal that a width ratio misses.
    """
    font = _font(path, index, SHAPE_PX)
    out: dict[str, Any] = {}

    def side_ink(mask: Image.Image, stem: tuple[int, int],
                 y_from: float, y_to: float) -> tuple[int, int]:
        """Rows in the band that carry ink left of or right of the stem."""
        pixels = mask.load()
        stem_left, stem_right = stem
        left_rows = right_rows = 0
        for y in range(int(mask.height * y_from), int(mask.height * y_to)):
            xs = [x for x in range(mask.width) if pixels[x, y] > 127]
            if not xs:
                continue
            if min(xs) <= stem_left - 2:
                left_rows += 1
            if max(xs) >= stem_right + 2:
                right_rows += 1
        return left_rows, right_rows

    for label, ch in (("one", "1"), ("I", "I"), ("l", "l")):
        mask, _l, _t = glyph_mask(font, ch)
        if mask.height < 8:
            for key in ("base_ratio", "top_ratio", "tail_dx", "flag_side", "arm_side"):
                out[f"{label}_{key}"] = None
            continue
        stem = _ink_columns(mask, mask.height // 2)
        mid = stem
        top = _ink_columns(mask, max(0, int(mask.height * 0.03)))
        bottom = _ink_columns(mask, mask.height - 1 - int(mask.height * 0.03))
        mid_width = (mid[1] - mid[0] + 1) if mid else 1
        out[f"{label}_base_ratio"] = (round((bottom[1] - bottom[0] + 1) / mid_width, 3)
                                     if bottom else None)
        out[f"{label}_top_ratio"] = (round((top[1] - top[0] + 1) / mid_width, 3)
                                    if top else None)
        left_rows, right_rows = side_ink(mask, stem, 0.0, 0.30) if stem else (0, 0)
        out[f"{label}_flag_side"] = left_rows
        out[f"{label}_arm_side"] = right_rows
        pixels = mask.load()

        def centroid(y_from: int, y_to: int) -> float | None:
            xs = [x for y in range(y_from, y_to) for x in range(mask.width)
                  if pixels[x, y] > 127]
            return sum(xs) / len(xs) if xs else None

        # a foot is the stem's centre of mass drifting sideways at the very bottom
        stem_centre = centroid(int(mask.height * 0.45), int(mask.height * 0.55))
        foot = centroid(int(mask.height * 0.88), mask.height)
        out[f"{label}_tail_dx"] = (round((foot - stem_centre) / font.getlength("M"), 4)
                                   if foot is not None and stem_centre is not None else None)

    zero = zero_style(path, index)
    out["zero_marked"] = zero.get("style") in ("dotted", "slashed")
    out["zero_style"] = zero.get("style")
    out["zero_counter_ink"] = zero.get("counter_ink")
    out["one_has_base"] = (out.get("one_base_ratio") or 0) > 1.6
    out["one_has_flag"] = (out.get("one_flag_side") or 0) > 1
    out["ell_has_flag"] = (out.get("l_flag_side") or 0) > 1
    out["ell_has_base"] = (out.get("l_base_ratio") or 0) > 1.6
    out["eye_has_serifs"] = ((out.get("I_top_ratio") or 0) > 1.6
                             and (out.get("I_base_ratio") or 0) > 1.6)
    out["ell_has_arm"] = (out.get("l_arm_side") or 0) > 1
    out["ell_has_tail"] = abs(out.get("l_tail_dx") or 0) > 0.04
    return out


def design_signature(path: str, index: int) -> dict[str, Any] | None:
    """Representation-insensitive outline signature.

    Bounding box and contour area per glyph. Two rebuilds of one design can differ
    in point count and in the last 0.1% of their area — a patched build converts
    curves — so exact point comparison reports them as different fonts. Bounding
    boxes are exact and areas are compared with a tolerance downstream.
    """
    from fontTools.pens.areaPen import AreaPen
    from fontTools.pens.boundsPen import BoundsPen
    try:
        font = TTFont(path, lazy=True, fontNumber=index if path.lower().endswith(".ttc") else 0)
    except Exception:
        return None
    signature: dict[str, Any] = {}
    try:
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap()
        for ch in "aegmRQ0@1lIi5S2Z":
            name = cmap.get(ord(ch))
            if not name or name not in glyph_set:
                continue
            bounds_pen = BoundsPen(glyph_set)
            glyph_set[name].draw(bounds_pen)
            area_pen = AreaPen(glyph_set)
            glyph_set[name].draw(area_pen)
            signature[ch] = [
                [round(value) for value in (bounds_pen.bounds or (0, 0, 0, 0))],
                round(area_pen.value),
                round(glyph_set[name].width),
            ]
    except Exception:
        return None
    finally:
        font.close()
    return signature or None


def measure_face(face: Face) -> dict[str, Any]:
    record: dict[str, Any] = asdict(face)
    font = TTFont(face.path, lazy=True, fontNumber=face.index if face.path.lower().endswith(".ttc") else 0)
    upem = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    widths = {font["hmtx"].metrics[cmap[code]][0]
              for code in range(0x20, 0x7F) if code in cmap}
    font.close()
    record["advance_units"] = min(widths) if widths else None
    record["advance_em"] = round(min(widths) / upem, 4) if widths else None
    record["advance_variance_units"] = (max(widths) - min(widths)) if widths else None
    record["strictly_monospaced"] = record["advance_variance_units"] == 0
    record["vertical"] = _safe("vertical", vertical_metrics, face.path, face.index)
    record["stroke"] = _safe("stroke", stroke_contrast, face.path, face.index)
    record["zero"] = _safe("zero", zero_style, face.path, face.index)
    record["cell"] = _safe("cell", cell_continuity, face.path, face.index)
    record["ink"] = _safe("ink", ink_density, face.path, face.index)
    record["coverage"] = _safe("coverage", coverage, face.path, face.index)
    record["confusion"] = _safe("confusion", confusability, face.path, face.index)
    record["disambiguation"] = _safe("disambiguation", disambiguation, face.path, face.index)
    record["design_fingerprint"] = _safe("fingerprint", design_fingerprint, face.path, face.index)
    record["design_signature"] = _safe("signature", design_signature, face.path, face.index)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/font-metrics.json")
    parser.add_argument("--inventory", default="docs/font-inventory.json")
    parser.add_argument("--family", action="append", default=[],
                        help="limit to these families (repeatable)")
    parser.add_argument("--extra-fonts", action="append", default=[],
                        help="also scan this directory, e.g. .cache/recent-fonts (repeatable)")
    args = parser.parse_args()
    extra_dirs = [os.path.abspath(directory) for directory in args.extra_fonts]

    faces, stats = load_faces(extra_dirs)
    print(f"scanned {stats['files']} font files: {stats['monospaced_faces']} monospaced faces, "
          f"{stats['proportional_faces']} proportional, {stats['unreadable']} unreadable")
    if args.family:
        wanted = {name.lower() for name in args.family}
        faces = [f for f in faces if f.family.lower() in wanted]
    by_family: dict[str, list[Face]] = {}
    for face in faces:
        by_family.setdefault(face.family, []).append(face)

    results = []
    for family, members in sorted(by_family.items()):
        for face in members:
            record = measure_face(face)
            results.append(record)
        print(f"{family}: {len(members)} faces")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(results, handle, indent=1, sort_keys=True)
    inventory = {
        "files_scanned": stats["files"],
        "files_unreadable": stats["unreadable"],
        "monospaced_faces": stats["monospaced_faces"],
        "proportional_faces_skipped": stats["proportional_faces"],
        "families_measured": len(by_family),
        "faces_measured": len(results),
        "directories": [d for d in FONT_DIRS if os.path.isdir(d)],
        "extra_directories": extra_dirs,
        "field": "monospaced",
    }
    inventory["skipped_families"] = stats["skipped_families"]
    with open(args.inventory, "w") as handle:
        json.dump(inventory, handle, indent=1, sort_keys=True)
    print(f"wrote {args.out}: {len(results)} faces, {len(by_family)} families")
    print(f"wrote {args.inventory}")


if __name__ == "__main__":
    main()
