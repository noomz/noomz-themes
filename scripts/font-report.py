#!/usr/bin/env python3
"""Render docs/font-report.html from docs/font-metrics.json.

The measurement lives in font-metrics.py. This file only turns those numbers into
a ranking and a document, and every number it prints comes back out of the JSON.

Scores are declared heuristics, not validated comfort scales. Where a band is
used instead of a monotone scale, the band is stated in the method section next
to the values actually observed over this font set.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, NamedTuple

# --------------------------------------------------------------------------
# axes and weights
# --------------------------------------------------------------------------

# Long-session ranking: reading a codebase all day.
MARATHON_WEIGHTS = {
    "distinction": 0.22,   # can you tell the glyphs apart without looking twice
    "aperture": 0.16,      # x-height, the thing that survives small sizes
    "density": 0.14,       # optical weight of a screenful of text
    "rhythm": 0.10,        # default line spacing at a given x-height
    "monoline": 0.10,      # stroke modulation
    "weights": 0.12,       # can you compensate for polarity
    "terminal": 0.10,      # rules, blocks, icons, separators
    "rendering": 0.06,     # hinting, outlines, axes, ligatures
}

# Screen-real-estate ranking: the palette report had a second viewpoint too.
DENSITY_WEIGHTS = {
    "compact": 0.28,       # columns per screen
    "aperture": 0.18,
    "density": 0.16,
    "distinction": 0.14,
    "rhythm": 0.08,
    "monoline": 0.06,
    "weights": 0.06,
    "rendering": 0.02,
    "terminal": 0.02,
}

# What each axis rests on. Rendered into the method section so the evidence status
# of every score is visible in the document rather than implied by it.
EVIDENCE = {
    "distinction": ("fit for purpose",
                    "Design rationale for code: 0/O and 1/l/I are separately encoded but "
                    "often alike (UTR #36). No trial measures the error-rate benefit."),
    "aperture": ("supported",
                 "Open letterforms and larger x-height improve small-size and glance "
                 "legibility (Beier et al. 2022; Dobres et al. 2016). In Dobres et al. "
                 "shrinking type from 4&nbsp;mm to 3&nbsp;mm cost a humanist ~26% and a "
                 "square grotesque ~62% in threshold &#8212; open forms degrade less. No "
                 "numeric optimum for x-height is established."),
    "density": ("direction only",
                "Very heavy or very light weights impair recognition (Beier et al. "
                "2022). The sweet band is this set's middle, not a measured optimum."),
    "rhythm": ("declared",
               "Line spacing affects comfort; no monospace line-height trial was found."),
    "monoline": ("direction only",
                 "Small-size cuts historically use lower stroke contrast (Beier et al. "
                 "2022; Dobres et al. 2016). No tolerable-modulation figure exists."),
    "weights": ("capability",
                "Tuning range available to you. No weight x polarity trial exists."),
    "compact": ("trade-off",
                "Condensed widths measurably impair letter recognition (Beier et al. "
                "2022), so columns per screen are bought at a legibility cost."),
    "terminal": ("fit for purpose",
                 "A TUI rule that does not reach the cell edge is a visible artefact. "
                 "Correctness, not comfort."),
    "rendering": ("capability",
                  "Hinting and outline format are robustness across rasterisers. No "
                  "study here compares rendering stacks for fatigue."),
}

AXIS_LABELS = {
    "distinction": "glyph distinction",
    "aperture": "x-height",
    "density": "optical density",
    "rhythm": "line spacing",
    "monoline": "monolinearity",
    "weights": "weight range",
    "compact": "columns per screen",
    "terminal": "terminal furniture",
    "rendering": "rendering stack",
}

RADAR_AXES = ["distinction", "aperture", "density", "rhythm",
              "monoline", "weights", "terminal", "rendering"]

# Stem targets by polarity. Light-on-dark text blooms, so it wants a heavier
# stroke than dark-on-light text of the same family. These are the bands the
# weight recommendation is computed against, in stem width as a fraction of em.
STEM_TARGET = {
    "light": (0.070, 0.090),
    "dark": (0.090, 0.112),
}

# Anchors that are declared, not derived from this font set, because the
# literature gives a direction and the extremes have to be placed by hand.
# (low, high) with high < low meaning higher raw values score lower.
DECLARED_SCALES = {
    "aperture": (0.46, 0.56),    # x-height in em: below .46 small text suffers
    "monoline": (1.35, 1.00),    # stroke contrast: 1.00 monolinear is the good end
}

# Distinction is scored by subtraction from a clean slate, because the measured
# area distances of modern coding fonts all sit above the level at which the eye
# confuses them: ranking 0.21 against 0.24 is noise. What is not noise is a pair
# that drops near zero, and a set with no deliberate disambiguating cue at all.
CRITICAL_PAIRS = {"0/O", "0/o", "1/l", "1/I", "l/I", "rn/m", "5/S", ";/:",
                  "8/B", "6/b", "g/q", "9/q", "vv/w", "ii/u"}
DEDUCTION = {
    "no_marked_zero": 15,
    "no_one_family_cue": 15,
    "pair_close": 10,          # raw distance below 0.20
    "pair_critical_close": 15,  # the same, on a pair that costs real debugging time
}
CLOSE_FLOOR = 0.20

# Differences below this are noise, as the method section states.
NOISE_POINTS = 3.0

# A pair is resolved when an explicit feature distinguishes it, whatever the
# silhouettes look like. This floor is declared, not measured: it says "this pair
# is separated by a deliberate cue" without pretending to be a distance.
RESOLVED_FLOOR = 0.30

# Config generation. Anchors are declared, and stated as such in the document.
#   size: the point size at which the measured x-height reaches this many pixels.
#     The literature backs the direction (small text is worse) not the number, so
#     the number is a floor to raise, not a target to aim at.
#   cell: the cell width to widen a narrow face toward. 0.55 em is the common
#     coding-font cell; below it the research says recognition suffers.
#   line: the line height to move a face's own default toward, in em.
CONFIG_ANCHORS = {"x_height_px": 6.5, "size_min": 10.5, "size_max": 17.0,
                  "size_step": 0.5, "cell_em": 0.55,
                  # the line target is not set here: it is the midpoint of the rhythm
                  # band, so the config and the score always agree on what is good
                  "emit_threshold_pct": 4.0}

# Terminals this machine actually has, with the config path, and the version the
# syntax was checked against. kitty dropped adjust_line_height in 0.4x in favour
# of modify_font cell_height, which is exactly the drift this table records.
CONFIG_TERMINALS = [
    ("kitty", "~/.config/kitty/kitty.conf", "conf"),
    ("ghostty", "~/.config/ghostty/config", "conf"),
    ("wezterm", "~/.wezterm.lua", "lua"),
    ("alacritty", "~/.config/alacritty/alacritty.toml", "toml"),
    ("iTerm2", "Settings &rarr; Profiles &rarr; Text", "gui"),
]

# Rules/separators a TUI draws and depends on the font to draw continuously.
FURNITURE_KEYS = ["underscore", "box_h", "box_v", "overline", "block_full"]

COVERAGE_GROUPS = ["powerline_pua", "box_drawing", "blocks", "braille", "arrows",
                   "geometric", "dingbats_checks", "math_ops", "nerd_icons",
                   "greek", "cyrillic"]

# Not coding fonts. Kept out of the ranking rather than ranked last, because a
# low score from an icon font would be a category error.
EXCLUDE_PATTERNS = [
    r"emoji", r"last\s?resort", r"symbols nerd font", r"^sketchybar",
    r"agent icons", r"^\.", r"^herdr",
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def scale(value: float, low: float, high: float) -> float:
    """Map low..high onto 0..100, inverted if high < low."""
    if high == low:
        return 50.0
    return clamp((value - low) / (high - low) * 100.0)


def plateau(value: float, sweet_low: float, sweet_high: float,
            edge_low: float, edge_high: float) -> float:
    """100 inside the sweet band, falling to 0 at the edges."""
    if sweet_low <= value <= sweet_high:
        return 100.0
    if value < sweet_low:
        return scale(value, edge_low, sweet_low)
    return scale(value, edge_high, sweet_high)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = clamp(fraction * (len(ordered) - 1), 0, len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def get(mapping: Any, *path: str, default: Any = None) -> Any:
    """Walk nested dicts, tolerating the 'error' placeholder from a failed stage."""
    node = mapping
    for key in path:
        if not isinstance(node, dict) or "error" in node and key not in node:
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


# --------------------------------------------------------------------------
# family assembly
# --------------------------------------------------------------------------

@dataclass
class Family:
    name: str
    aliases: list[str]
    fingerprint: str
    faces: list[dict[str, Any]]
    representative: dict[str, Any]
    excluded: bool = False
    scores: dict[str, float] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    # catalogue rows from docs/recent-fonts.json this design was downloaded for
    recent: list[dict[str, Any]] = field(default_factory=list)
    installed: bool = True
    installed_sibling: str = ""   # a separately drawn build of this design that is installed
    font_family: str = ""         # the name inside the file, when the row shows another

    @property
    def webfont_only(self) -> bool:
        """True when every measured file is a catalogue webfont of at most four faces."""
        return (not self.installed and bool(self.recent)
                and all(row["source"] == "webfont" for row in self.recent))

    # -- measured passthrough -------------------------------------------------
    @property
    def vertical(self) -> dict[str, Any]:
        return self.representative.get("vertical") or {}

    @property
    def ink(self) -> dict[str, Any]:
        return self.representative.get("ink") or {}

    @property
    def stroke(self) -> dict[str, Any]:
        return self.representative.get("stroke") or {}

    @property
    def cell(self) -> dict[str, Any]:
        return self.representative.get("cell") or {}

    @property
    def confusion(self) -> dict[str, Any]:
        return self.representative.get("confusion") or {}

    @property
    def disambiguation(self) -> dict[str, Any]:
        return self.representative.get("disambiguation") or {}

    @property
    def coverage(self) -> dict[str, Any]:
        best: dict[str, Any] = {}
        for face in self.faces:
            group = face.get("coverage") or {}
            if "error" in group:
                continue
            for key, value in group.items():
                if isinstance(value, (int, float)) and value > best.get(key, -1):
                    best[key] = value
        return best

    @property
    def weight_ladder(self) -> list[dict[str, Any]]:
        ladder = []
        for face in self.faces:
            stroke = face.get("stroke") or {}
            if "error" in stroke or stroke.get("stem_em") is None:
                continue
            ladder.append({
                "subfamily": face.get("subfamily") or "",
                "weight_class": face.get("weight_class") or 400,
                "stem_em": stroke["stem_em"],
                "italic": bool(face.get("is_italic")),
                "contrast": stroke.get("contrast"),
            })
        return sorted(ladder, key=lambda item: (item["weight_class"], item["italic"]))

    @property
    def upright_weights(self) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        for item in self.weight_ladder:
            if item["italic"]:
                continue
            seen.setdefault(item["weight_class"], item)
        return [seen[key] for key in sorted(seen)]

    @property
    def has_italic(self) -> bool:
        return any(face.get("is_italic") for face in self.faces)

    @property
    def is_variable(self) -> bool:
        return any(face.get("is_variable") for face in self.faces)

    @property
    def has_ligatures(self) -> bool:
        return bool(family_features(self) & {"liga", "calt"})

    def weight_for(self, polarity: str) -> dict[str, Any] | None:
        low, high = STEM_TARGET[polarity]
        centre = (low + high) / 2
        candidates = self.upright_weights
        if not candidates:
            return None
        inside = [item for item in candidates if low <= item["stem_em"] <= high]
        pool = inside or candidates
        best = min(pool, key=lambda item: abs(item["stem_em"] - centre))
        best = dict(best)
        best["in_band"] = low <= best["stem_em"] <= high
        best["band"] = (low, high)
        return best


def normalize_name(name: str) -> str:
    """Family name with the patch and variant tokens removed."""
    text = name.lower()
    for token in ("nerd font", "patched", " nerds", " nerd", " nf ", "mono", "propo"):
        text = text.replace(token, " ")
    if text.endswith(" nf"):
        text = text[:-3]
    return re.sub(r"[^a-z0-9]+", "", text)


def signatures_match(first: Any, second: Any, tolerance: float = 0.01,
                     allow_outliers: int = 2) -> bool:
    """Same design rebuilt, allowing for a curve conversion and its area drift.

    Most glyphs have to agree exactly and the rest within tolerance, because a
    patched build can come from an earlier version of the same design that redrew
    one or two glyphs. Two glyphs out of sixteen is the allowance; a face that
    differs more than that is a different drawing and keeps its own row.
    """
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    if "error" in first or "error" in second or not first or not second:
        return False
    if set(first) != set(second) or len(first) < 8:
        return False
    outliers = 0
    for ch in first:
        box_a, area_a, width_a = first[ch]
        box_b, area_b, width_b = second[ch]
        largest = max(abs(area_a), abs(area_b))
        area_off = (abs(area_a - area_b) / largest) if largest else 0.0
        if box_a == box_b and width_a == width_b and area_off <= tolerance:
            continue
        outliers += 1
        if outliers > allow_outliers:
            return False
    return True


def download_key(record: dict[str, Any], cache_root: str) -> str | None:
    """The catalogue entry a face was downloaded for, read from its cache path."""
    path = record.get("path") or ""
    if not cache_root or not path.startswith(cache_root):
        return None
    return path[len(cache_root):].split(os.sep, 1)[0]


def build_families(records: list[dict[str, Any]], cache_root: str = "") -> list[Family]:
    """Group faces into families, then merge families that are the same design.

    Bundling by name first keeps Regular, Bold and Italic together. Merging then
    folds a Nerd-Font-patched build onto its upstream design, and a Mono or Propo
    variant onto the family it varies, because those differ in coverage and cell
    forcing rather than in letterforms. Two families merge when their rasterised
    glyphs hash the same, or when their names normalise to the same design and
    their outline signatures agree within one percent of contour area — the
    tolerance a curve conversion moves. A relabelled reissue with different
    outlines stays a separate row, because it is a different drawing. Faces downloaded
    for one catalogue entry always merge, because webfonts and width variants often
    carry a separate family name per style and the catalogue lists them as one font.
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_name.setdefault(record["family"], []).append(record)
    blocks: list[Family] = []
    for name, faces in by_name.items():
        representative = _pick_regular(faces)
        fingerprint = representative.get("design_fingerprint")
        if not fingerprint or isinstance(fingerprint, dict):
            fingerprint = f"solo:{representative.get('path')}#{representative.get('index')}"
        blocks.append(Family(name=name, aliases=[], fingerprint=fingerprint,
                             faces=faces, representative=representative))

    parent = list(range(len(blocks)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(one: int, other: int) -> None:
        root_one, root_other = find(one), find(other)
        if root_one != root_other:
            parent[root_other] = root_one

    for index, block in enumerate(blocks):
        for other_index in range(index + 1, len(blocks)):
            other = blocks[other_index]
            same_build = block.fingerprint == other.fingerprint
            key = download_key(block.representative, cache_root)
            same_download = key is not None and key == download_key(other.representative, cache_root)
            same_name = normalize_name(block.name) == normalize_name(other.name)
            same_outline = signatures_match(
                block.representative.get("design_signature"),
                other.representative.get("design_signature"))
            if same_build or same_download or (same_name and same_outline):
                union(index, other_index)

    merged: dict[int, list[Family]] = {}
    for index, block in enumerate(blocks):
        merged.setdefault(find(index), []).append(block)

    families: list[Family] = []
    for group in merged.values():
        faces = [face for family in group for face in family.faces]
        names = sorted({family.name for family in group})
        canonical = _canonical_name(names)
        owner = next((family for family in group if family.name == canonical), group[0])
        excluded = any(re.search(pattern, name, re.I)
                       for name in names for pattern in EXCLUDE_PATTERNS)
        reason = "icon or emoji font" if excluded else ""
        if not excluded and not _has_latin(owner.representative):
            excluded = True
            reason = "no Latin coverage"
        family = Family(
            name=canonical,
            aliases=[name for name in names if name != canonical],
            fingerprint=owner.fingerprint,
            faces=faces,
            representative=owner.representative,
            excluded=excluded,
        )
        if reason:
            family.details["excluded_reason"] = reason
        families.append(family)
    return families


def cache_root_of(manifest: dict[str, Any]) -> str:
    return os.path.abspath(manifest["cache"]) + os.sep


def attach_recent(families: list[Family], manifest: dict[str, Any]) -> None:
    """Tie each design to the catalogue rows its files were downloaded for.

    The cache layout is the record: every downloaded face sits under <cache>/<key>/,
    so provenance comes from the path that was measured, not from matching names.

    A download of a design that is already installed adds nothing to that design's
    score. The installed copy is what this machine renders, and crediting it with a
    richer release would move a score without any installed file changing.
    """
    root = cache_root_of(manifest)
    rows = {row["key"]: row for row in manifest["fonts"]}
    for family in families:
        keys = {download_key(face, root) for face in family.faces} - {None}
        family.recent = [rows[key] for key in sorted(keys) if key in rows]
        kept = [face for face in family.faces if download_key(face, root) is None]
        family.installed = bool(kept)
        if family.installed and len(kept) != len(family.faces):
            family.faces = kept
            if download_key(family.representative, root) is not None:
                family.representative = _pick_regular(kept)
    installed_names = {normalize_name(name): family.name for family in families if family.installed
                       for name in [family.name, *family.aliases]}
    for family in families:
        if family.installed or len(family.recent) != 1:
            continue
        family.font_family = family.representative.get("family") or family.name
        catalogue_name = family.recent[0]["name"]
        if catalogue_name != family.name:
            family.aliases = sorted({*family.aliases, family.name})
            family.name = catalogue_name
        sibling = installed_names.get(normalize_name(catalogue_name))
        if sibling:
            family.installed_sibling = sibling


def _canonical_name(names: list[str]) -> str:
    """Prefer the name a terminal config would most likely use."""
    def rank(name: str) -> tuple[int, int, int]:
        patched = 0 if "nerd font" in name.lower() else 1
        mono = 0 if re.search(r"\bmono\b| nf$", name, re.I) else 1
        return (patched, mono, len(name))
    return sorted(names, key=rank)[0]


def _pick_regular(faces: list[dict[str, Any]]) -> dict[str, Any]:
    upright = [face for face in faces if not face.get("is_italic")]
    pool = upright or faces

    def rank(face: dict[str, Any]) -> tuple[int, int, int]:
        subfamily = (face.get("subfamily") or "").lower()
        preferred = 0 if subfamily in ("regular", "roman", "book", "text", "normal") else 1
        return (preferred, abs((face.get("weight_class") or 400) - 400),
                1 if face.get("is_italic") else 0)
    return sorted(pool, key=rank)[0]


def _has_latin(record: dict[str, Any]) -> bool:
    vertical = record.get("vertical") or {}
    if "error" in vertical:
        return False
    if vertical.get("ascii_coverage") is not None:
        return (vertical.get("ascii_coverage") or 0) > 0.95
    return (vertical.get("cmap_size") or 0) > 200


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def confusion_feature_score(family: Family) -> tuple[float, str]:
    """How many of the classic ambiguous sets are resolved by an explicit cue."""
    features = family.disambiguation
    cues = cue_table(features)
    zero_marked = bool(cues["zero"])
    stroke_cues = sorted(cues["one"] | cues["ell"] | cues["eye"])
    score = 100.0 * ((0.5 if zero_marked else 0.0)
                     + 0.5 * min(1.0, len(stroke_cues) / 2.0))
    zero_note = "zero " + ("marked" if zero_marked else "plain")
    stroke_note = (", ".join(stroke_cues) if stroke_cues
                   else "no cue on the one, the ell or the eye")
    return score, f"{zero_note} \u00b7 1/l/I cues: {stroke_note}"


def _cues(features: dict[str, Any], prefix: str) -> set[str]:
    return {name for name in ("flag", "base", "arm", "tail")
            if features.get(f"{prefix}_has_{name}")}


def cue_table(features: dict[str, Any]) -> dict[str, set[str]]:
    """The deliberate disambiguating cues each member of the ambiguous sets carries.

    The one gets a flag and a base, the ell gets a flag, a top arm or a foot, the
    capital eye gets serifs. The zero is handled on its own because a mark inside
    it is not a stroke of the same kind.
    """
    return {
        "zero": {"mark"} if features.get("zero_marked") else set(),
        "one": _cues(features, "one"),
        "ell": _cues(features, "ell"),
        "eye": {"serifs"} if features.get("eye_has_serifs") else set(),
    }


def feature_resolved(features: dict[str, Any], pair: str) -> bool:
    """True when deliberate cues keep this pair apart on their own.

    Two members of a set are apart when each carries a cue and the two cue sets
    differ: a one with a flag and a base against an ell with a flag alone is a
    resolved pair, while two members carrying the same cues are not resolved
    however different their proportions happen to measure.
    """
    cues = cue_table(features)
    one, ell, eye = cues["one"], cues["ell"], cues["eye"]
    if pair in ("0/O", "0/o"):
        return bool(cues["zero"])
    if pair == "1/l":
        return bool(one) and bool(ell) and one != ell
    if pair == "1/I":
        return bool(one) and bool(eye)
    if pair == "l/I":
        return bool(eye) or bool(ell)
    if pair == "1/|":
        return bool(one)
    if pair == "l/|":
        return bool(ell)
    return False


def pair_distances(family: Family) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Raw and feature-adjusted per-pair distances, plus which pairs were lifted."""
    raw = get(family.confusion, "design", "pairs", default={}) or {}
    raw = {pair: value for pair, value in raw.items() if isinstance(value, (int, float))}
    effective: dict[str, float] = {}
    lifted: list[str] = []
    for pair, value in raw.items():
        if value < RESOLVED_FLOOR and feature_resolved(family.disambiguation, pair):
            effective[pair] = RESOLVED_FLOOR
            lifted.append(pair)
        else:
            effective[pair] = value
    return raw, effective, lifted


def furniture_score(family: Family) -> tuple[float, str]:
    cell = family.cell
    checks = [cell.get(key) for key in FURNITURE_KEYS]
    available = [check for check in checks if isinstance(check, dict)]
    if not available:
        return 0.0, "no rule glyphs measured"
    passed = sum(1 for check in available if check.get("continuous"))
    continuity = passed / len(available)
    coverage = family.coverage
    group_scores = [coverage.get(f"{group}_pct") or 0.0 for group in COVERAGE_GROUPS]
    # icons matter more than Greek here, but only after the rules are right
    icon = coverage.get("powerline_pua_pct") or 0.0
    nerd = coverage.get("nerd_icons_pct") or 0.0
    average = sum(group_scores) / len(group_scores)
    score = 100.0 * (0.55 * continuity + 0.20 * icon + 0.10 * nerd + 0.15 * average)
    return clamp(score), f"{passed}/{len(available)} rules continuous"


def weights_score(family: Family) -> tuple[float, str]:
    """Capability, not comfort: how much stem weight the family lets you choose."""
    upright = family.upright_weights
    count = len(upright)
    base = {0: 0, 1: 25, 2: 45, 3: 60, 4: 72, 5: 82, 6: 88}.get(count, 92 if count > 6 else 0)
    stems = [item["stem_em"] for item in upright]
    variable = any(face.get("is_variable") for face in family.faces)
    if variable:
        base += 8
    detail = (f"{count} upright weight{'s' if count != 1 else ''}, "
              f"stem {min(stems):.3f}\u2013{max(stems):.3f} em" if stems
              else "no weights measured")
    if variable:
        detail += " \u00b7 variable"
    return clamp(float(base)), detail


def rendering_score(family: Family) -> tuple[float, str]:
    """Robustness of the file, not comfort. Ligature presence is reported, not scored:
    no trial in the reviewed set measures a ligature against comprehension."""
    score = 0.0
    notes = []
    verticals = [face.get("vertical") or {} for face in family.faces]
    verticals = [item for item in verticals if "error" not in item]
    if any(item.get("has_instructions") for item in verticals):
        score += 40
        notes.append("hinted")
    if any(item.get("has_gasp") for item in verticals):
        score += 5
        notes.append("gasp table")
    kinds = {face.get("file_kind") for face in family.faces}
    if "glyf" in kinds:
        score += 15
        notes.append("TrueType outlines")
    if any(item.get("is_variable") for item in verticals):
        score += 20
        notes.append("variable")
    italic_faces = [face for face in family.faces if face.get("is_italic")]
    if italic_faces:
        roman = family.representative.get("design_fingerprint")
        distinct = any(face.get("design_fingerprint") != roman for face in italic_faces)
        score += 20 if distinct else 8
        notes.append("true italic" if distinct else "oblique only")
    else:
        notes.append("no italic")
    return clamp(score), ", ".join(notes)


def score_family(family: Family, bands: dict[str, tuple[float, float]]) -> None:
    scores: dict[str, float] = {}
    details: dict[str, str] = {}

    vertical = family.vertical
    ink = family.ink

    x_height = vertical.get("x_height_em") or 0.0
    scores["aperture"] = scale(x_height, *DECLARED_SCALES["aperture"])
    details["aperture"] = f"x-height {x_height:.3f} em"

    density = ink.get("ink_body") or 0.0
    scores["density"] = plateau(density, *bands["density"])
    details["density"] = f"ink {density:.4f} of the cell"

    line_height = vertical.get("default_line_height_em") or 0.0
    scores["rhythm"] = plateau(line_height, *bands["rhythm"])
    details["rhythm"] = f"default line height {line_height:.3f} em"

    contrast = get(family.stroke, "contrast", default=None)
    if contrast is None:
        scores["monoline"] = 0.0
        details["monoline"] = "unmeasured"
    else:
        scores["monoline"] = scale(contrast, *DECLARED_SCALES["monoline"])
        details["monoline"] = f"stroke contrast {contrast:.2f}:1"

    raw_pairs, effective, lifted = pair_distances(family)
    features = family.disambiguation
    score = 100.0
    deductions: list[str] = []
    if not features.get("zero_marked"):
        score -= DEDUCTION["no_marked_zero"]
        deductions.append(f"\u2212{DEDUCTION['no_marked_zero']} unmarked zero")
    cues = cue_table(features)
    # the set needs two cues to stay separable: one on the one, one on the ell or
    # the eye, so that 1, l and I differ from each other pairwise
    cue_count = len(cues["one"] | cues["ell"] | cues["eye"])
    if cue_count < 2:
        score -= DEDUCTION["no_one_family_cue"]
        deductions.append(f"\u2212{DEDUCTION['no_one_family_cue']} 1/l/I carries {cue_count} cue"
                          f"{'s' if cue_count != 1 else ''}")

    close_pairs = sorted(
        ((pair, value) for pair, value in raw_pairs.items()
         if pair not in lifted and value < CLOSE_FLOOR),
        key=lambda item: item[1])
    if close_pairs:
        penalty = 0
        for pair, _value in close_pairs:
            penalty += (DEDUCTION["pair_critical_close"] if pair in CRITICAL_PAIRS
                        else DEDUCTION["pair_close"])
        score -= penalty
        listed = ", ".join(f"{pair} {value:.3f}" for pair, value in close_pairs[:4])
        deductions.append(f"\u2212{penalty} {listed}")

    scores["distinction"] = clamp(score)
    worst_pair = min(effective, key=lambda key: effective[key]) if effective else None
    worst = effective.get(worst_pair) if worst_pair else None
    details["distinction"] = (
        f"nearest pair {worst_pair} at {worst:.3f}" if worst is not None else "unmeasured")
    details["distinction_deductions"] = (" \u00b7 ".join(deductions) if deductions
                                         else "no deductions: every classic set resolved")
    details["distinction_features"] = confusion_feature_score(family)[1]

    scores["weights"], details["weights"] = weights_score(family)
    scores["terminal"], details["terminal"] = furniture_score(family)
    scores["rendering"], details["rendering"] = rendering_score(family)

    advance = ink.get("advance_px") or 0.0
    cols = ink.get("cols_per_1000px") or 0.0
    scores["compact"] = scale(cols, *bands["cols"])
    details["compact"] = f"{cols:.1f} columns per 1000 px at {ink.get('advance_px', 0):.2f} px/cell"

    family.scores = {key: round(value, 1) for key, value in scores.items()}
    family.details = details


def composite(scores: dict[str, float], weights: dict[str, float]) -> float:
    total = 0.0
    for key, weight in weights.items():
        total += scores.get(key, 0.0) * weight
    return round(total, 1)


def compute_bands(families: list[Family]) -> dict[str, tuple[float, float]]:
    def flat(values: list[Any]) -> list[float]:
        return [value for value in values if isinstance(value, (int, float))]

    effective_worsts = []
    for family in families:
        _raw, effective, _lifted = pair_distances(family)
        if effective:
            effective_worsts.append(min(effective.values()))
    values = {
        "confusion": effective_worsts,
        "contrast": flat([get(f.stroke, "contrast") for f in families]),
        "cols": flat([f.ink.get("cols_per_1000px") for f in families]),
        "density": flat([f.ink.get("ink_body") for f in families]),
        "rhythm": flat([f.vertical.get("default_line_height_em") for f in families]),
        "x_height": flat([f.vertical.get("x_height_em") for f in families]),
    }
    bands: dict[str, tuple[float, ...]] = {
        # observed spread, used for the two axes that are rankings rather than
        # quality scales: how far apart two glyphs are, and how narrow a cell is
        "confusion": (round(percentile(values["confusion"], 0.10), 4),
                      round(percentile(values["confusion"], 0.95), 4)),
        "cols": (round(percentile(values["cols"], 0.05), 2),
                 round(percentile(values["cols"], 0.95), 2)),
        # observed reference values, printed in the method for context
        "contrast_observed": (round(percentile(values["contrast"], 0.05), 3),
                              round(percentile(values["contrast"], 0.95), 3)),
        "x_height_observed": (round(percentile(values["x_height"], 0.05), 4),
                              round(percentile(values["x_height"], 0.95), 4)),
    }
    # density and rhythm are bands: the middle is best and both ends are worse,
    # so the sweet band is the middle of what was observed, not the whole spread
    density_sorted = sorted(values["density"])
    rhythm_sorted = sorted(values["rhythm"])
    bands["density"] = (round(percentile(density_sorted, 0.30), 4),
                        round(percentile(density_sorted, 0.70), 4),
                        round(min(density_sorted) * 0.90, 4),
                        round(max(density_sorted) * 1.05, 4))
    bands["rhythm"] = (round(percentile(rhythm_sorted, 0.30), 4),
                       round(percentile(rhythm_sorted, 0.70), 4),
                       round(min(rhythm_sorted) * 0.95, 4),
                       round(max(rhythm_sorted) * 1.05, 4))
    bands["contrast"] = DECLARED_SCALES["monoline"]
    bands["x_height"] = DECLARED_SCALES["aperture"]
    return bands


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def base_css(path: str) -> str:
    """Reuse the sibling report's stylesheet so the two documents match."""
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        return ""
    match = re.search(r"<style>(.*?)</style>", text, re.S)
    return match.group(1) if match else ""


EXTRA_CSS = """
.specimen{background:#fff;border:1px solid var(--line);padding:10px 12px;margin-bottom:14px}
.specimen.light .screen{color:#000;background:var(--spec-bg)}
.specimen .screen{font-synthesis:none}
.specimen figcaption{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
font-size:11.5px;color:var(--dim);margin-bottom:7px}
.specimen figcaption code{font-size:12px;color:var(--ink)}
.specimen figcaption .who{margin-left:auto;font-size:10.5px}
.fontname{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.matrix{font-size:12px}
.matrix td,.matrix th{padding:4px 5px;text-align:center}
.matrix td.name{text-align:left;font-size:11.5px}
.matrix .yes{color:var(--ok);font-weight:700}
.matrix .no{color:var(--bad);font-weight:700}
.matrix .part{color:var(--mid);font-weight:700}
.ladder{list-style:none;padding:0;margin:6px 0 0;font-size:12px}
.ladder li{display:grid;grid-template-columns:96px 1fr 74px;gap:8px;align-items:center;
padding:2px 0;border-bottom:1px dotted #efede6}
.ladder .bar{background:#efece3;height:9px;position:relative;border-radius:2px;overflow:hidden}
.ladder .bar i{position:absolute;left:0;top:0;bottom:0;background:#4a4a4a}
.ladder .bar i.light{background:#7d8f5f}
.ladder .bar i.dark{background:#6b5b8a}
.ladder .stem{color:var(--dim);font-variant-numeric:tabular-nums;text-align:right}
.ladder .pick{font-weight:700}
.zerochip{display:inline-block;width:14px;height:14px;border:1px solid var(--line);
border-radius:3px;vertical-align:-3px;margin-right:5px}
.feat{font-size:11.5px;color:var(--dim)}
.glyphstrip{font-size:19px;letter-spacing:.02em;margin:4px 0 8px;white-space:nowrap;overflow:hidden}
.glyphstrip b{font-weight:400;color:#b9b3a4}
.scorebadge.low{background:#7a7a7a}
.callout{background:#fff;border:1px solid var(--line);border-left:3px solid var(--mid);
padding:12px 14px;margin:14px 0;font-size:13.5px}
.callout b{font-size:13.5px}
.warn{border-left-color:var(--bad)}
.axis-note{font-size:11.5px;color:var(--dim);margin:2px 0 0}
.weights-table td.name{font-size:12px}
details.cfg{background:#fff;border:1px solid var(--line);margin:0 0 10px;padding:0}
details.cfg>summary{cursor:pointer;padding:9px 12px;font-size:13px;
display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
details.cfg>summary code{font-size:13px;font-weight:600}
details.cfg[open]>summary{border-bottom:1px solid var(--line)}
.cfg-meta{color:var(--dim);font-size:11.5px}
.cfg-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0;
border-top:0}
@media(max-width:880px){.cfg-grid{grid-template-columns:1fr}}
figure.cfg-block{margin:0;padding:10px 12px 12px;border-right:1px solid var(--line);
border-bottom:1px solid var(--line);min-width:0}
figure.cfg-block figcaption{font-size:11.5px;color:var(--dim);margin-bottom:6px;
display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
figure.cfg-block figcaption code{font-size:11.5px;color:var(--ink)}
pre.cfg{background:#f7f5ef;border:1px solid var(--line);border-radius:3px;margin:0;
padding:8px 10px;font:11.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
overflow-x:auto;white-space:pre;color:#222}
button.copy{margin-left:auto;font:11px/1 -apple-system,sans-serif;background:#fff;
border:1px solid var(--line);border-radius:3px;padding:3px 7px;cursor:pointer;
color:var(--dim)}
button.copy:hover{border-color:var(--accent);color:var(--accent)}
button.copy.done{border-color:var(--ok);color:var(--ok)}
th button.sort{text-transform:none;letter-spacing:normal}
.explorer .g-axes,.explorer .g-coverage,.explorer .g-facts{display:none}
.explorer.show-axes .g-axes,.explorer.show-coverage .g-coverage,
.explorer.show-facts .g-facts{display:table-cell}
.inband{background:#eef4e6;padding:0 2px}
.board-controls{background:#fff;border:1px solid var(--line);padding:8px 10px;margin:8px 0;
font-size:12px}
.board-controls .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:3px 0}
.board-controls .lbl{color:var(--dim);width:52px;flex:none}
.board-controls label{color:var(--ink);margin-right:6px}
.pick{font:11.5px/1.2 -apple-system,sans-serif;background:#fff;border:1px solid var(--line);
border-radius:12px;padding:3px 9px;cursor:pointer;color:var(--ink)}
.pick:hover{border-color:var(--accent)}
.pick[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
.board-search{font:12px -apple-system,sans-serif;border:1px solid var(--line);border-radius:3px;
padding:3px 6px;margin-left:auto;width:150px}
.board-count{color:var(--dim);font-variant-numeric:tabular-nums}
@media(max-width:600px){.board-controls .lbl{width:100%}.board-search{margin-left:0}}
@media print{.board-controls{display:none}}
@media print{details.cfg{break-inside:avoid}details.cfg>summary{list-style:none}
.cfg-grid{display:block}figure.cfg-block{border-right:0}}
"""

BOARD_JS = r'''
(function(){
  var NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)/;
  function value(cell){
    if (!cell || cell.tagName !== 'TD') { return null; }
    if (cell.hasAttribute('data-v')) { return cell.getAttribute('data-v'); }
    var text = cell.textContent.trim();
    return text === '—' ? '' : text;
  }
  function dataRows(body){
    return Array.prototype.filter.call(body.rows, function(row){ return row.cells[0].tagName === 'TD'; });
  }
  Array.prototype.forEach.call(document.querySelectorAll('table.sortable tbody tr'), function(row, i){
    row.setAttribute('data-base', i);
  });
  function sortTable(table, index, direction){
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
        // missing values sink in both directions, ties keep the ranked order
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
  var board = document.getElementById('board');
  var onBoardSort = null;
  Array.prototype.forEach.call(document.querySelectorAll('table.sortable'), function(table){
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
        if (table === board && onBoardSort) { onBoardSort(th.getAttribute('data-key'), direction); }
        else { sortTable(table, index, direction); }
      });
    });
    table.sortTo = function(index, direction){ current = {index: index, direction: direction}; };
  });
  if (!board) { return; }

  var controls = document.querySelector('.board-controls');
  var views = JSON.parse(document.getElementById('board-views').textContent);
  var heads = Array.prototype.slice.call(board.tHead.rows[0].cells);
  var keys = heads.map(function(th){ return th.getAttribute('data-key'); });
  var search = controls.querySelector('.board-search');
  var empty = document.querySelector('.board-empty');
  var divider = board.querySelector('tr.divider th');
  var total = board.querySelectorAll('tbody tr[data-name]').length;
  function fresh(){ return {view: 'all', sort: 'rank', dir: 'up', f: {}, show: [], q: ''}; }
  function fromView(key){
    var v = views[key];
    var f = {};
    Object.keys(v.f).forEach(function(k){ f[k] = v.f[k].slice(); });
    return {view: key, sort: v.sort, dir: v.dir, f: f, show: v.show.slice(), q: ''};
  }
  var state = fresh();

  function render(){
    var index = keys.indexOf(state.sort);
    if (index < 0) { state.sort = 'rank'; index = 0; }
    sortTable(board, index, state.dir);
    board.sortTo(index, state.dir);
    ['axes', 'coverage', 'facts'].forEach(function(group){
      var on = state.show.indexOf(group) >= 0;
      board.classList.toggle('show-' + group, on);
      controls.querySelector('[data-group="' + group + '"]').checked = on;
    });
    if (divider) {
      divider.colSpan = heads.filter(function(th){ return th.offsetParent !== null || th.getClientRects().length; }).length;
    }
    var q = state.q.toLowerCase();
    var shown = 0;
    Array.prototype.forEach.call(board.querySelectorAll('tbody tr[data-name]'), function(row){
      var ok = !q || row.getAttribute('data-name').indexOf(q) >= 0;
      Object.keys(state.f).forEach(function(facet){
        var wanted = state.f[facet];
        if (ok && wanted.length) { ok = wanted.indexOf(row.getAttribute('data-f-' + facet)) >= 0; }
      });
      row.hidden = !ok;
      if (ok) { shown += 1; }
    });
    var references = board.querySelector('tbody.references');
    if (references) { references.hidden = !references.querySelector('tr[data-name]:not([hidden])'); }
    controls.querySelector('.board-count').textContent =
      shown === total ? total + ' fonts' : 'showing ' + shown + ' of ' + total;
    empty.hidden = shown > 0;
    Array.prototype.forEach.call(controls.querySelectorAll('[data-facet]'), function(chip){
      var wanted = state.f[chip.getAttribute('data-facet')] || [];
      chip.setAttribute('aria-pressed', String(wanted.indexOf(chip.getAttribute('data-value')) >= 0));
    });
    Array.prototype.forEach.call(controls.querySelectorAll('[data-view]'), function(chip){
      chip.setAttribute('aria-pressed', String(chip.getAttribute('data-view') === state.view));
    });
    if (search.value !== state.q) { search.value = state.q; }
  }

  function toHash(){
    if (state.view === 'all') { return ''; }
    var params = new URLSearchParams();
    if (state.view) { params.set('view', state.view); return '#board?' + params.toString(); }
    params.set('sort', state.sort);
    params.set('dir', state.dir);
    var f = Object.keys(state.f).filter(function(k){ return state.f[k].length; })
      .map(function(k){ return k + ':' + state.f[k].join('.'); });
    if (f.length) { params.set('f', f.join(',')); }
    if (state.show.length) { params.set('show', state.show.join(',')); }
    if (state.q) { params.set('q', state.q); }
    return '#board?' + params.toString();
  }
  function fromHash(hash){
    if (hash.indexOf('#board?') !== 0) { return null; }
    var params = new URLSearchParams(hash.slice(7));
    var view = params.get('view');
    if (view && views[view]) { return fromView(view); }
    var next = fresh();
    next.view = '';
    next.sort = params.get('sort') || 'rank';
    next.dir = params.get('dir') === 'down' ? 'down' : 'up';
    (params.get('f') || '').split(',').filter(Boolean).forEach(function(pair){
      var parts = pair.split(':');
      next.f[parts[0]] = (parts[1] || '').split('.').filter(Boolean);
    });
    next.show = (params.get('show') || '').split(',').filter(function(g){
      return ['axes', 'coverage', 'facts'].indexOf(g) >= 0; });
    next.q = params.get('q') || '';
    return next;
  }
  function changed(){
    render();
    var hash = toHash();
    history.replaceState(null, '', location.pathname + location.search + hash);
  }

  onBoardSort = function(key, direction){
    state.view = '';
    state.sort = key;
    state.dir = direction;
    changed();
  };
  controls.addEventListener('click', function(event){
    var chip = event.target.closest('button');
    if (!chip) { return; }
    if (chip.hasAttribute('data-view')) { state = fromView(chip.getAttribute('data-view')); }
    else if (chip.classList.contains('reset')) { state = fresh(); }
    else if (chip.hasAttribute('data-facet')) {
      var facet = chip.getAttribute('data-facet');
      var wanted = state.f[facet] = state.f[facet] || [];
      var at = wanted.indexOf(chip.getAttribute('data-value'));
      if (at >= 0) { wanted.splice(at, 1); } else { wanted.push(chip.getAttribute('data-value')); }
      state.view = '';
    } else { return; }
    changed();
  });
  controls.addEventListener('change', function(event){
    var group = event.target.getAttribute('data-group');
    if (!group) { return; }
    state.show = state.show.filter(function(g){ return g !== group; });
    if (event.target.checked) { state.show.push(group); }
    state.view = '';
    changed();
  });
  search.addEventListener('input', function(){
    state.q = search.value.trim();
    state.view = '';
    changed();
  });
  controls.hidden = false;
  var linked = fromHash(location.hash);
  if (linked) {
    state = linked;
    render();
    board.scrollIntoView();
  } else {
    render();
  }
})();
'''


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def radar_svg(series: list[tuple[str, str, dict[str, float]]], title: str,
              axes: list[str] = RADAR_AXES) -> str:
    """Spoke chart in the same shape as the palette report's."""
    import math
    width, height = 560, 470
    cx, cy = 280, 228
    radius = 128
    label_radius = radius + 26
    count = len(axes)
    start = -math.pi / 2

    def point(index: int, value: float, extra: float = 0.0) -> tuple[float, float]:
        angle = start + index * 2 * math.pi / count
        reach = radius * (value / 100.0) + extra
        return cx + reach * math.cos(angle), cy + reach * math.sin(angle)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
             f'class="radar" role="img" aria-labelledby="radar-fonts">',
             f'<title id="radar-fonts">{esc(title)}</title>']
    for ring in (25, 50, 75, 100):
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in
                          (point(index, ring) for index in range(count)))
        css = ' class="ring outer"' if ring == 100 else ' class="ring"'
        parts.append(f'<polygon points="{points}"{css}/>')
        label_x, label_y = point(0, ring)
        parts.append(f'<text x="{label_x + 5:.1f}" y="{label_y + 4:.1f}" class="tick">{ring}</text>')
    for index in range(count):
        x, y = point(index, 100)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.2f}" y2="{y:.2f}" class="spoke"/>')
        lx, ly = point(index, 100, label_radius - radius)
        anchor = "middle"
        if lx > cx + 8:
            anchor = "start"
        elif lx < cx - 8:
            anchor = "end"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                     f'class="axis-label">{esc(AXIS_LABELS[axes[index]])}</text>')
    for index, (label, color, values) in enumerate(series):
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in
                          (point(axis_index, values.get(axis, 0.0))
                           for axis_index, axis in enumerate(axes)))
        parts.append(
            f'<polygon points="{points}" data-series="{index}" '
            f'style="fill:{color};fill-opacity:.14;stroke:{color};stroke-width:2"/>')
    parts.append("</svg>")
    legend = ['<ul class="legend">']
    for index, (label, color, values) in enumerate(series):
        total = sum(values.get(axis, 0.0) for axis in axes) / len(axes)
        legend.append(
            f'<li data-series="{index}" tabindex="0">'
            f'<svg class="swatch-line" width="14" height="10" aria-hidden="true">'
            f'<rect width="14" height="10" rx="2" fill="{color}"/></svg>'
            f'<span class="lg-name">{esc(label)}</span>'
            f'<span class="lg-score">{total:.0f} mean</span></li>')
    legend.append("</ul>")
    return "\n".join(parts) + "\n" + "\n".join(legend)


def matrix_table(families: list[Family]) -> str:
    """The ambiguous sets, per font: the measured distance and the deliberate cues.

    Sorted by the closest measured pair rather than by score, so the row that
    carries the most risk is the one you read first.
    """
    compared = []
    for family in families:
        raw_pairs, _effective, _lifted = pair_distances(family)
        relevant = {pair: value for pair, value in raw_pairs.items()
                    if pair in ("0/O", "1/l", "1/I", "l/I", "rn/m", ";/:")}
        compared.append((min(relevant.values()) if relevant else 1.0, family))
    compared.sort(key=lambda item: item[0])

    rows = []
    for _closest, family in compared:
        features = family.disambiguation
        raw_pairs, effective, lifted = pair_distances(family)
        cues = cue_table(features)

        def pair_cell(name: str) -> str:
            raw = raw_pairs.get(name)
            if raw is None:
                return '<span class="part">&mdash;</span>'
            css = "yes" if raw >= 0.29 else ("part" if raw >= 0.18 else "no")
            mark = '<span class="flag">*</span>' if name in lifted else ""
            return f'<span class="{css}">{raw:.02f}</span>{mark}'

        def cue_cell(cue_set: set[str]) -> str:
            if not cue_set:
                return '<span class="no">none</span>'
            return f'<span class="yes">{esc(", ".join(sorted(cue_set)))}</span>'

        zero_style = features.get("zero_style") or "plain"
        rows.append(
            "<tr>"
            f'<td class="name"><a href="#{esc(slug(family.name))}">{esc(family.name)}</a></td>'
            f'<td>{zero_style}</td>'
            f'<td>{pair_cell("0/O")}</td>'
            f'<td>{pair_cell("1/l")}</td>'
            f'<td>{pair_cell("1/I")}</td>'
            f'<td>{pair_cell("l/I")}</td>'
            f'<td>{pair_cell("rn/m")}</td>'
            f'<td>{pair_cell(";/:")}</td>'
            f'<td>{cue_cell(cues["zero"])}</td>'
            f'<td>{cue_cell(cues["one"])}</td>'
            f'<td>{cue_cell(cues["ell"])}</td>'
            f'<td>{cue_cell(cues["eye"])}</td>'
            "</tr>")
    return (table("<tr><th>font</th><th>zero</th><th>0/O</th><th>1/l</th><th>1/I</th>"
                  "<th>l/I</th><th>rn/m</th><th>; / :</th><th>zero cue</th>"
                  "<th>one cue</th><th>ell cue</th><th>eye cue</th></tr>",
                  "".join(rows), "ambiguity matrix", "matrix sortable")
            + "<p class='axis-note'>The first seven numeric columns are the raw measured "
            "symmetric-difference distance for that pair: below 0.18 is a problem, "
            "0.18&ndash;0.29 is workable, above that the shapes are clearly apart. A "
            "value marked * is below the confusability floor in its outlines but is "
            "lifted to the declared resolution floor for scoring, because the cue "
            "columns show the pair is separated deliberately. The cue columns are "
            "measured, not read from documentation.</p>")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def preview_status(family: Family) -> str:
    if family.installed:
        return "installed"
    if family.webfont_only:
        return "catalogue webfont only"
    if family.installed_sibling:
        return "patched build installed"
    return "not installed"


def face_gap(family: Family, face: str) -> str:
    """Why a face cannot be shown for this design, or empty when it can.

    A design that is not installed can only show what the catalogue hosts, which can be
    less than the release that was measured.
    """
    def is_bold(weight: Any) -> bool:
        return str(weight) in ("bold", "600", "700", "800", "900")

    wants_bold, wants_italic = "bold" in face, "italic" in face
    if not family.installed:
        hosted = (family.recent[0].get("webfont_faces") or []) if family.recent else []
        if any(item.get("file") and is_bold(item["weight"]) == wants_bold
               and (item["style"] == "italic") == wants_italic for item in hosted):
            return ""
    has_face = any(
        bool(item.get("is_italic")) == wants_italic
        and (not wants_bold or item.get("is_bold") or item.get("is_variable")
             or (item.get("weight_class") or 400) >= 600)
        for item in family.faces)
    if not has_face:
        return "not in this font"
    return "" if family.installed else "in the release, not in the preview file"


def face_rows(family: Family) -> list[list[Span]]:
    rows = []
    for face in FACE_CSS:
        gap = face_gap(family, face)
        label = Span(f"{face:<12}", "dim")
        rows.append([label, Span(gap, "dim")] if gap
                    else [label, Span(FACE_SAMPLE, "fg", face)])
    return rows


def preview_span(span: Span) -> str:
    sample = span.text == FACE_SAMPLE
    marker = f' class="face-sample" data-face="{span.face}"' if sample else ""
    return (f'<span{marker} style="color:var(--syn-{span.role});{FACE_CSS[span.face]}">'
            f"{esc(span.text)}</span>")


def terminal_preview(family: Family, rank: int, polarity: str, background: str) -> str:
    """One font in a terminal session, at a fixed size and its own default line height."""
    lines = "".join(
        '<div class="ln">' + "".join(preview_span(span) for span in spans) + "</div>"
        for spans in PREVIEW_LINES + face_rows(family))
    line_height = family.vertical.get("default_line_height_em") or 1.2
    return (
        f'<figure class="term specimen {polarity}" data-font="{esc(family.name)}">'
        f'<figcaption><code class="fontname">#{rank} {esc(family.name)}</code>'
        f'<span class="flag">{family.scores.get("marathon", 0):.1f} &middot; '
        f'{preview_status(family)}</span>'
        f'<span class="flag preview-missing" hidden>font unavailable, showing a fallback</span>'
        f'<span class="who">{polarity}</span></figcaption>'
        f"<div class=\"screen\" style=\"font-family:'{esc(family.name)}', ui-monospace, monospace;"
        f'font-size:{PREVIEW_PX}px;line-height:{line_height:.3f};background:{background}">'
        f"{lines}</div></figure>")


def preview_section(ranked: list[Family], light: dict[str, str], dark: dict[str, str]) -> str:
    def pairs(rows: list[tuple[int, Family]]) -> str:
        return "".join(terminal_preview(family, rank, "light", light["bg"])
                       + terminal_preview(family, rank, "dark", dark["bg"])
                       for rank, family in rows)

    numbered = list(enumerate(ranked, start=1))
    shown, rest = numbered[:PREVIEW_OPEN], numbered[PREVIEW_OPEN:]
    more = (f'<details class="preview-more"><summary>Show the other {len(rest)} designs'
            f'</summary><div class="term-grid">{pairs(rest)}</div></details>' if rest else "")
    return f"""<h2>Terminal preview</h2>
<p class="note">Every ranked design in the same terminal session, in rank order, at
{PREVIEW_PX}&nbsp;px and the font's own default line height. Palettes are the sibling report's
winners, modus-operandi and catppuccin-mocha, read from <code>themes/claude/</code>.</p>
<p class="note">Installed designs render only on a machine that has them, and uninstalled
designs load from a copy of the programmingfonts.org webfont served with this report. That file
can be an older build than the release that was measured, so the measured numbers are the
record. Files over 2.5&nbsp;MiB are not served. A preview that cannot get its font says so in
its caption.</p>
<p class="note">Browser synthesis is off, so every bold and italic here is a real drawn face,
not a slanted or thickened regular. The last four rows of each preview show the four styles
side by side, and a row names the reason when a style cannot be shown. Where a font has no
italic, its italic comment renders upright.</p>
<div class="term-grid">{pairs(shown)}</div>
{more}
"""


def ladder_html(family: Family) -> str:
    ladder = family.upright_weights
    if not ladder:
        return '<p class="note">No upright weights measured.</p>'
    light_pick = family.weight_for("light")
    dark_pick = family.weight_for("dark")
    low, high = 0.04, 0.14
    items = []
    for item in ladder:
        stem = item["stem_em"]
        position = clamp((stem - low) / (high - low) * 100, 0, 100)
        kind = ""
        if light_pick and item["weight_class"] == light_pick["weight_class"]:
            kind = " light"
        if dark_pick and item["weight_class"] == dark_pick["weight_class"]:
            kind = " dark"
        name = item["subfamily"] or str(item["weight_class"])
        if sum(1 for other in ladder if (other["subfamily"] or str(other["weight_class"])) == name) > 1:
            name = f'{name} ({item["weight_class"]})'
        items.append(
            f'<li><span class="{"pick" if kind else ""}">{esc(name)}</span>'
            f'<span class="bar"><i class="{kind.strip()}" style="width:{position:.1f}%"></i></span>'
            f'<span class="stem">{stem:.3f} em</span></li>')
    return ('<ul class="ladder">' + "".join(items) + "</ul>"
            '<p class="axis-note">Bars are stem width as a fraction of the em box. '
            'The band that suits light mode is 0.070&ndash;0.090 em and the band that '
            'suits dark mode is 0.090&ndash;0.112 em; a filled bar is a weight inside it.</p>')


def ligature_note(family: Family) -> str:
    tags = family_features(family)
    interesting = [tag for tag in ("liga", "calt", "zero", "ss01", "ss02", "cv01")
                   if tag in tags]
    if not interesting:
        return "none of liga, calt, zero, ss01, ss02, cv01"
    return ", ".join(interesting) + " (present; no trial measures a ligature) "


def card_html(family: Family, rank: int) -> str:
    vertical = family.vertical
    ink = family.ink
    cell = family.cell
    confusion = family.confusion
    features = family.disambiguation
    coverage = family.coverage
    light_pick = family.weight_for("light")
    dark_pick = family.weight_for("dark")

    ladder_note = []
    if light_pick:
        ladder_note.append(f"light &rarr; {esc(light_pick['subfamily'] or light_pick['weight_class'])}"
                           f" ({light_pick['stem_em']:.3f} em"
                           f"{'' if light_pick['in_band'] else ', outside band'})")
    if dark_pick:
        ladder_note.append(f"dark &rarr; {esc(dark_pick['subfamily'] or dark_pick['weight_class'])}"
                           f" ({dark_pick['stem_em']:.3f} em"
                           f"{'' if dark_pick['in_band'] else ', outside band'})")

    axes = "".join(
        f"<li><b>{family.scores.get(axis, 0):.0f}</b> {esc(AXIS_LABELS[axis])}</li>"
        for axis in RADAR_AXES)

    worst = get(confusion, "design", "worst")
    worst_render = get(confusion, "render", "worst")
    aliases = ""
    if family.aliases:
        aliases = (f'<p class="meta">{"also installed as" if family.installed else "file names"} '
                   + ", ".join(f"<code>{esc(name)}</code>" for name in family.aliases[:6])
                   + "</p>")

    details = [
        ("outlines", esc(family.representative.get("file_kind") or "&mdash;")
         + f" &middot; {vertical.get('glyph_count', '&mdash;')} glyphs"),
        ("cell", f"{ink.get('advance_px', 0):.2f} px &middot; "
                 f"{ink.get('cols_per_1000px', 0):.1f} cols/1000 px &middot; "
                 f"x-height {vertical.get('x_height_em', 0):.3f} em &middot; "
                 f"cap {vertical.get('cap_height_em', 0):.3f} em"),
        ("density", f"{ink.get('ink_body', 0):.4f} ink/cell at 13 px "
                    f"&middot; stroke contrast {get(family.stroke, 'contrast', default=0):.2f}:1"),
        ("distinction", f"nearest pair at design size {worst if worst is not None else '&mdash;'}"
                        f" ({get(confusion, 'design', 'worst_pair', default='&mdash;')}), "
                        f"at 13 px {worst_render if worst_render is not None else '&mdash;'}"),
        ("distinction cost", esc(family.details.get("distinction_deductions", ""))),
        ("features", esc(family.details.get("distinction_features", ""))),
        ("features present", esc(ligature_note(family))),
        ("furniture", esc(family.details.get("terminal", ""))
         + f" &middot; powerline {coverage.get('powerline_pua_pct', 0) * 100:.0f}%"
           f" &middot; braille {coverage.get('braille_pct', 0) * 100:.0f}%"
           f" &middot; box {coverage.get('box_drawing_pct', 0) * 100:.0f}%"),
        ("rendering", esc(family.details.get("rendering", ""))),
        ("weights", esc(family.details.get("weights", ""))),
    ]
    if not (features.get("zero_marked")):
        pass

    return f"""<article class="card" id="{esc(slug(family.name))}">
<h3>{esc(family.name)} <span class="scorebadge">{family.scores.get('marathon', 0):.1f}</span>
<span class="scorebadge low">{family.scores.get('density_first', 0):.1f} density</span></h3>
<p class="meta">#{rank} long-session &middot; <span class="fontname">{esc(family.representative.get('full_name') or family.name)}</span>
&middot; {len(family.faces)} {'installed' if family.installed else 'measured'} face{'s' if len(family.faces) != 1 else ''}{recent_marker(family)}</p>
{aliases}
<p class="glyphstrip" style="font-family:'{esc(family.name)}', monospace">0Oo 1lI| 5S 2Z 8B gq9 ;:, rn m</p>
<ul class="axescore">{axes}</ul>
{table("<tr><th>measured</th><th>value</th></tr>",
       "".join(f"<tr><td><code>{key}</code></td><td>{value}</td></tr>"
               for key, value in details),
       f"card {family.name}", "roles")}
<div class="repair"><h4>Weight for each polarity</h4>
<p class="note">{' &middot; '.join(ladder_note) if ladder_note else 'no weight data'}</p>
{ladder_html(family)}
</div>
</article>"""


def closest_pair_cell(family: Family) -> str:
    """The closest *measured* pair, with a marker when a cue resolves it anyway."""
    raw, _effective, lifted = pair_distances(family)
    if not raw:
        return "&mdash;"
    pair = min(raw, key=lambda key: raw[key])
    marker = '<span class="flag">cue</span>' if pair in lifted else ""
    return f'<span class="dimtxt">{esc(pair)}</span> {raw[pair]:.3f}{marker}'


def check_columns(table_html: str, label: str) -> str:
    """Fail loudly when a table's header and its rows disagree on column count.

    A row one cell short does not break the render: it silently shifts every value
    left and leaves the last column empty, which is exactly how a blank line-height
    column shipped once.
    """
    head = re.search(r"<thead>.*?</thead>", table_html, re.S)
    body = re.search(r"<tbody>(.*?)</tbody>", table_html, re.S)
    if not head or not body:
        return table_html
    headers = len(re.findall(r"<th[ >]", head.group(0)))
    for offset, row in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S), start=1):
        cells = len(re.findall(r"<td[ >]", row))
        if cells != headers:
            raise ValueError(
                f"{label}: row {offset} has {cells} cells but the header has {headers} "
                f"— columns would shift")
    return table_html


def table(header: str, body: str, label: str, css_class: str = "matrix",
          style: str = "") -> str:
    """Build a table, with the header/row column counts checked before it ships."""
    attributes = f" class='{css_class}'" if css_class else ""
    if style:
        attributes += f" style='{style}'"
    markup = (f"<div class='table-scroll'><table{attributes}>"
              f"<thead>{header}</thead><tbody>{body}</tbody></table></div>")
    return check_columns(markup, label)


def recent_marker(family: Family) -> str:
    if family.installed or not family.recent:
        return ""
    year = max(row["year"] for row in family.recent)
    label = f"{year}, webfont only" if family.webfont_only else str(year)
    state = "patched build installed" if family.installed_sibling else "not installed"
    return f' <span class="flag">{label}, {state}</span>'


def fmt(value: Any, digits: int = 1) -> str:
    return "&mdash;" if value is None else f"{value:.{digits}f}"


def family_features(family: Family) -> set[str]:
    tags: set[str] = set()
    for face in family.faces:
        vertical = face.get("vertical") or {}
        if "error" not in vertical:
            tags.update(vertical.get("features") or [])
    return tags


# Licence text from name ID 13, first match wins. Read from the file, so it covers
# installed fonts too. Catalogue rows add their own label for files that carry none.
LICENCES = [
    ("OFL", re.compile(r"open ?font ?licen[cs]e|\bOFL\b|scripts\.sil\.org", re.I)),
    ("Apache", re.compile(r"apache licen[cs]e", re.I)),
    ("MIT", re.compile(r"\bMIT licen[cs]e|permission is hereby granted, free of charge", re.I)),
    ("GPL", re.compile(r"\bGPL\b|general public licen[cs]e", re.I)),
    ("Ubuntu", re.compile(r"ubuntu font licen[cs]e", re.I)),
    ("Bitstream Vera", re.compile(r"bitstream vera", re.I)),
    ("CC", re.compile(r"creative commons", re.I)),
    ("ParaType", re.compile(r"paratype", re.I)),
    ("EULA", re.compile(r"\bEULA\b|monotype\.com/.*licen", re.I)),
    ("Apple", re.compile(r"\bapple\b", re.I)),
    ("Microsoft", re.compile(r"\bmicrosoft\b", re.I)),
]
CATALOGUE_LICENCES = {"SIL OFL": "OFL", "MIT": "MIT", "GNU GPL": "GPL", "permissive": "permissive",
                      "Apache": "Apache", "commercial": "commercial"}
FREE_LICENCES = {"OFL", "Apache", "MIT", "GPL", "Ubuntu", "Bitstream Vera", "CC", "ParaType",
                 "permissive"}


def licence_of(family: Family) -> str:
    texts = [str((face.get("vertical") or {}).get("license") or "") for face in family.faces]
    texts += [" ".join((face.get("vertical") or {}).get("license_url") or [])
              for face in family.faces]
    text = " ".join(texts)
    for label, pattern in LICENCES:
        if pattern.search(text):
            return label
    for row in family.recent:
        if row.get("license") in CATALOGUE_LICENCES:
            return CATALOGUE_LICENCES[row["license"]]
    # Fonts that ship with macOS often carry no licence text and are not redistributable.
    if family.faces and all(str(face.get("path", "")).startswith("/System/Library/")
                            for face in family.faces):
        return "macOS"
    return "other" if text.strip() else "unknown"


def licence_kind(family: Family) -> str:
    licence = licence_of(family)
    if licence in FREE_LICENCES:
        return "free"
    return "unknown" if licence == "unknown" else "restricted"


def coverage_share(family: Family, key: str) -> float | None:
    value = family.coverage.get(f"{key}_pct")
    return None if value is None else round(value * 100, 1)


def release_year(family: Family) -> int | None:
    return max((row["year"] for row in family.recent), default=None)


def worst_pair_distance(family: Family) -> float | None:
    raw, _effective, _lifted = pair_distances(family)
    return min(raw.values()) if raw else None


class Column(NamedTuple):
    """One leaderboard column. The browser sorts on `value` and shows `cell`.

    `first` is the direction of the first click: down for a column where more is
    better, up for one scored against a band, where neither end is better.
    """
    key: str
    label: str
    value: Any
    cell: Any
    first: str = "down"
    group: str = "core"
    num: bool = True


def board_columns(bands: dict[str, tuple[float, float]]) -> list[Column]:
    def score(key: str) -> Any:
        return lambda family, rank: family.scores.get(key)

    def in_band(value: float | None, band: str, digits: int) -> str:
        """Shade a value inside its scoring band: these columns have no better end."""
        low, high = bands[band][:2]
        if value is not None and low <= value <= high:
            return f'<span class="inband">{fmt(value, digits)}</span>'
        return fmt(value, digits)

    def delta(family: Family) -> float:
        return round(family.scores.get("marathon", 0) - family.scores.get("density_first", 0), 1)

    def name_cell(family: Family, rank: int | None) -> str:
        return (f'<a href="#{esc(slug(family.name))}"><code>{esc(family.name)}</code></a>'
                f'{recent_marker(family) if rank else ""}')

    def share(key: str) -> Column:
        label = {"nerd_icons": "nerd<br>icons %", "powerline_pua": "power-<br>line %",
                 "box_drawing": "box<br>drawing %", "braille": "braille<br>%",
                 "cyrillic": "cyrillic<br>%", "greek": "greek<br>%", "cjk_smoke": "CJK<br>%"}[key]
        return Column(key, label, lambda f, r: coverage_share(f, key),
                      lambda f, r: fmt(coverage_share(f, key), 0), group="coverage")

    def yes(value: bool) -> str:
        return "yes" if value else "no"

    columns = [
        Column("rank", "#", lambda f, r: r, lambda f, r: str(r) if r else "&mdash;", first="up"),
        Column("font", "font", lambda f, r: f.name.lower(), name_cell, first="up", num=False),
        Column("marathon", "long-<br>session", score("marathon"),
               lambda f, r: fmt(f.scores.get("marathon"))),
        Column("density_first", "density-<br>first", score("density_first"),
               lambda f, r: fmt(f.scores.get("density_first"))),
        Column("delta", "&Delta;", lambda f, r: delta(f) if r else None,
               lambda f, r: (f'<span class="delta {"up" if delta(f) > 0 else "down"}">'
                             f'{delta(f):+.1f}</span>') if r else "&mdash;"),
        Column("x_height", "x-height<br>em", lambda f, r: f.vertical.get("x_height_em"),
               lambda f, r: fmt(f.vertical.get("x_height_em"), 3)),
        Column("cols", "cols/<br>1000px", lambda f, r: f.ink.get("cols_per_1000px"),
               lambda f, r: fmt(f.ink.get("cols_per_1000px"))),
        Column("worst_pair", "worst<br>pair", lambda f, r: worst_pair_distance(f),
               lambda f, r: closest_pair_cell(f)),
        Column("zero", "zero", lambda f, r: f.disambiguation.get("zero_style") or "plain",
               lambda f, r: esc(f.disambiguation.get("zero_style") or "plain"),
               first="up", num=False),
        Column("contrast", "stroke<br>contrast", lambda f, r: get(f.stroke, "contrast"),
               lambda f, r: fmt(get(f.stroke, "contrast"), 2), first="up"),
        Column("ink", "ink<br>density", lambda f, r: f.ink.get("ink_body"),
               lambda f, r: in_band(f.ink.get("ink_body"), "density", 4), first="up"),
        Column("weights", "weights", lambda f, r: len(f.upright_weights),
               lambda f, r: str(len(f.upright_weights))),
        Column("line_height", "line<br>height", lambda f, r: f.vertical.get("default_line_height_em"),
               lambda f, r: in_band(f.vertical.get("default_line_height_em"), "rhythm", 3),
               first="up"),
    ]
    columns += [Column(f"axis_{axis}", esc(AXIS_LABELS[axis]).replace(" ", "<br>", 1),
                       score(axis), (lambda key: lambda f, r: fmt(f.scores.get(key), 0))(axis),
                       group="axes")
                for axis in RADAR_AXES]
    columns += [share(key) for key in ("nerd_icons", "powerline_pua", "box_drawing", "braille",
                                       "cyrillic", "greek", "cjk_smoke")]
    columns += [
        Column("year", "year", lambda f, r: release_year(f),
               lambda f, r: fmt(release_year(f), 0), group="facts"),
        Column("licence", "licence", lambda f, r: licence_of(f),
               lambda f, r: esc(licence_of(f)), first="up", group="facts", num=False),
        Column("faces", "faces", lambda f, r: len(f.faces), lambda f, r: str(len(f.faces)),
               group="facts"),
        Column("italic", "real<br>italic", lambda f, r: yes(f.has_italic),
               lambda f, r: yes(f.has_italic), group="facts", num=False),
        Column("variable", "variable", lambda f, r: yes(f.is_variable),
               lambda f, r: yes(f.is_variable), group="facts", num=False),
        Column("ligatures", "liga-<br>tures", lambda f, r: yes(f.has_ligatures),
               lambda f, r: yes(f.has_ligatures), group="facts", num=False),
    ]
    return columns


COLUMN_GROUPS = [("axes", "axis scores"), ("coverage", "glyph coverage"),
                 ("facts", "licence and faces")]


class Facet(NamedTuple):
    """A filter group. Chips in one facet are alternatives, separate facets all apply."""
    key: str
    label: str
    value: Any
    chips: tuple[tuple[str, str], ...]


def board_facets(cutoff: int | None) -> list[Facet]:
    def full(key: str, threshold: float = 95.0) -> Any:
        return lambda f: "full" if (coverage_share(f, key) or 0) >= threshold else "partial"

    def dark_band(family: Family) -> str:
        pick = family.weight_for("dark")
        return "yes" if pick and pick["in_band"] else "no"

    return [
        Facet("installed", "where", lambda f: "yes" if f.installed else "no",
              (("yes", "installed here"), ("no", "not installed"))),
        Facet("licence", "licence", licence_kind,
              (("free", "free licence"), ("restricted", "restricted"))),
        Facet("new", "release", lambda f: "yes" if release_year(f) else "no",
              (("yes", f"released after {cutoff}" if cutoff else "recent release"),)),
        Facet("zero", "zero", lambda f: f.disambiguation.get("zero_style") or "plain",
              (("slashed", "slashed zero"), ("dotted", "dotted zero"), ("plain", "plain zero"))),
        Facet("ligatures", "ligatures", lambda f: "yes" if f.has_ligatures else "no",
              (("yes", "ligatures"), ("no", "no ligatures"))),
        Facet("italic", "italic", lambda f: "yes" if f.has_italic else "no",
              (("yes", "real italic"),)),
        Facet("variable", "variable", lambda f: "yes" if f.is_variable else "no",
              (("yes", "variable"),)),
        Facet("dark", "dark mode", dark_band, (("yes", "weight in the dark band"),)),
        # A Nerd Fonts patch fills 90% of the sampled icon range, which has unassigned points.
        Facet("nerd", "icons", full("nerd_icons", 85.0), (("full", "Nerd icons built in"),)),
        Facet("cyrillic", "cyrillic", full("cyrillic"), (("full", "full Cyrillic"),)),
        Facet("greek", "greek", full("greek"), (("full", "full Greek"),)),
    ]


class View(NamedTuple):
    key: str
    label: str
    sort: str
    direction: str
    facets: dict[str, list[str]]
    groups: list[str]


BOARD_VIEWS = [
    View("all", "Long-session ranking", "rank", "up", {}, []),
    View("small-screen", "Small screen", "density_first", "down", {}, []),
    View("hex", "Hex and IDs", "axis_distinction", "down", {"zero": ["slashed", "dotted"]}, ["axes"]),
    View("dark", "Dark mode", "axis_weights", "down", {"dark": ["yes"]}, ["axes"]),
    View("icons", "Icons built in", "rank", "up", {"nerd": ["full"]}, ["coverage"]),
    View("new-free", "New and free", "rank", "up", {"new": ["yes"], "licence": ["free"]},
         ["facts"]),
    View("not-latin", "Beyond Latin", "rank", "up", {"cyrillic": ["full"], "greek": ["full"]},
         ["coverage"]),
]


def sort_attr(value: Any) -> str:
    if value is None:
        return ""
    return f' data-v="{esc(value if isinstance(value, str) else repr(round(float(value), 6)))}"'


def board_row(family: Family, rank: int | None, columns: list[Column],
              facets: list[Facet]) -> str:
    names = " ".join([family.name, *family.aliases]).lower()
    data = "".join(f' data-f-{facet.key}="{esc(facet.value(family))}"' for facet in facets)
    cells = "".join(
        f'<td class="{" ".join(c for c in ("num" if column.num else "", f"g-{column.group}") if c)}"'
        f'{sort_attr(column.value(family, rank))}>{column.cell(family, rank)}</td>'
        for column in columns)
    return f'<tr data-name="{esc(names)}"{data}>{cells}</tr>'


def board_controls(columns: list[Column], facets: list[Facet], total: int) -> str:
    states = {view.key: {"sort": view.sort, "dir": view.direction, "f": view.facets,
                         "show": view.groups} for view in BOARD_VIEWS}
    views_json = json.dumps(states).replace("</", "<\\/")
    views = "".join(f'<button type="button" class="pick view" data-view="{view.key}">'
                    f'{esc(view.label)}</button>' for view in BOARD_VIEWS)
    chips = "".join(
        f'<button type="button" class="pick" data-facet="{facet.key}" data-value="{value}" '
        f'aria-pressed="false">{esc(label)}</button>'
        for facet in facets for value, label in facet.chips)
    groups = "".join(f'<label><input type="checkbox" data-group="{key}"> {esc(label)}</label>'
                     for key, label in COLUMN_GROUPS)
    return f"""<script type="application/json" id="board-views">{views_json}</script>
<div class="board-controls" hidden>
<div class="row"><span class="lbl">views</span>{views}</div>
<div class="row"><span class="lbl">filter</span>{chips}</div>
<div class="row"><span class="lbl">columns</span>{groups}
<input type="search" class="board-search" placeholder="find a font" aria-label="find a font">
<span class="board-count" aria-live="polite">{total} fonts</span>
<button type="button" class="pick reset">reset</button></div>
</div>"""


def leaderboard(rows: list[Family], title: str, note: str,
                bands: dict[str, tuple[float, float]], cutoff: int | None,
                reference: list[Family] | None = None) -> str:
    columns = board_columns(bands)
    facets = board_facets(cutoff)
    head = "<thead><tr>" + "".join(
        f'<th class="{" ".join(c for c in ("num" if column.num else "", f"g-{column.group}") if c)}"'
        f' data-key="{column.key}" data-first="{column.first}">{column.label}</th>'
        for column in columns) + "</tr></thead>"
    body = "".join(board_row(family, rank, columns, facets)
                   for rank, family in enumerate(rows, start=1))
    reference_block = ""
    if reference:
        reference_block = (
            f'<tbody class="references"><tr class="divider"><th colspan="'
            f'{sum(column.group == "core" for column in columns)}">'
            "Reference only &middot; unranked</th></tr>"
            + "".join(board_row(family, None, columns, facets) for family in reference)
            + "</tbody>")
    markup = check_columns(
        '<table class="board sortable explorer" id="board">' + head + "<tbody>" + body
        + "</tbody>" + reference_block + "</table>", f"leaderboard {title}")
    return (f"<h3>{esc(title)}</h3><p class=\"note\">{note}</p>"
            + board_controls(columns, facets, len(rows) + len(reference or []))
            + '<p class="board-empty note" hidden>No font matches every filter. '
              "Remove one to see more.</p>"
            + "<div class=\"table-scroll\">" + markup + "</div>")


def nearest_pair_note(family: Family) -> str:
    """Plain-language summary of the closest measured pair and how it is handled."""
    raw_pairs, _effective, lifted = pair_distances(family)
    if not raw_pairs:
        return "no pairs measured"
    pair = min(raw_pairs, key=lambda key: raw_pairs[key])
    value = raw_pairs[pair]
    if pair in lifted:
        return f"{pair} at {value:.3f}, resolved by a cue"
    if value < 0.18:
        return f"{pair} at {value:.3f} &mdash; close, and nothing resolves it"
    return f"{pair} at {value:.3f}"


def config_plan(family: Family, bands: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """Everything a terminal snippet needs, derived from the measurements."""
    vertical = family.vertical
    x_height = vertical.get("x_height_em") or 0.0
    advance = family.ink.get("advance_px") or 0.0
    size_px = family.ink.get("advance_px") and None or None
    size_pt = (CONFIG_ANCHORS["x_height_px"] / x_height) if x_height else 12.0
    size_pt = max(CONFIG_ANCHORS["size_min"], min(CONFIG_ANCHORS["size_max"], size_pt))
    step = CONFIG_ANCHORS["size_step"]
    size_pt = round(size_pt / step) * step

    advance_em = (advance / 13.0) if advance else 0.0
    # The cell anchor is a floor: a face narrower than it can be widened, but a
    # face wider than it is already legible and squeezing the cell would only
    # press the glyphs together.
    cell_delta = ((CONFIG_ANCHORS["cell_em"] / advance_em - 1) * 100) if advance_em else 0.0
    cell_delta = max(0.0, cell_delta)
    line_target = round((bands["rhythm"][0] + bands["rhythm"][1]) / 2, 3)
    line_height = vertical.get("default_line_height_em") or 0.0
    line_delta = ((line_target / line_height - 1) * 100) if line_height else 0.0
    threshold = CONFIG_ANCHORS["emit_threshold_pct"]

    bold = next((item for item in family.upright_weights if item["weight_class"] == 700), None)
    italic = next((item for item in family.weight_ladder
                   if item["italic"] and item["weight_class"] == 400), None)
    bold_italic = next((item for item in family.weight_ladder
                        if item["italic"] and item["weight_class"] == 700), None)
    coverage = family.coverage
    needs_symbol_fallback = (coverage.get("powerline_pua_pct") or 0) < 0.5
    return {
        "name": family.font_family or family.name,
        "size": size_pt,
        "size_reason": (f"x-height {x_height:.3f} em reaches "
                        f"{CONFIG_ANCHORS['x_height_px']:.1f} px at this size"),
        "cell_delta": round(cell_delta, 1) if abs(cell_delta) >= threshold else 0.0,
        "line_delta": round(line_delta, 1) if abs(line_delta) >= threshold else 0.0,
        "line_target": line_target,
        "line_height_em": line_height,
        "line_band": bands["rhythm"],
        "advance_em": advance_em,
        "regular": family.representative.get("subfamily") or "Regular",
        "bold": (bold or {}).get("subfamily"),
        "italic": (italic or {}).get("subfamily"),
        "bold_italic": (bold_italic or {}).get("subfamily"),
        "has_ligatures": family.has_ligatures,
        "needs_symbol_fallback": needs_symbol_fallback,
        "symbol_fallback": "Symbols Nerd Font Mono",
    }


def _pct(value: float) -> str:
    """Display form, always signed, for the summary line."""
    return f"{value:+.0f}%"


def _pct_arg(value: float) -> str:
    """Argument form for a config file: a leading plus is not always parsed."""
    return f"{value:.0f}%" if value > 0 else f"{value:.0f}%"


def config_snippets(plan: dict[str, Any]) -> dict[str, str]:
    """One ready-to-paste block per terminal, in that terminal's own syntax."""
    name = plan["name"]
    size = plan["size"]
    cell = plan["cell_delta"]
    line = plan["line_delta"]
    bold = plan["bold"] or "Bold"
    italic = plan["italic"] or "Italic"
    bold_italic = plan["bold_italic"] or "Bold Italic"
    out: dict[str, str] = {}

    kitty = [f'font_family      family="{name}"']
    kitty.append(f"bold_font        family='{name}' style='{bold}'"
                 if plan["bold"] else "bold_font        auto  # family ships no bold")
    kitty.append(f"italic_font      family='{name}' style='{italic}'"
                 if plan["italic"] else "italic_font      auto  # no true italic installed")
    kitty.append(f"bold_italic_font family='{name}' style='{bold_italic}'"
                 if plan["bold_italic"] else "bold_italic_font auto")
    kitty.append(f"font_size {size}")
    if line:
        kitty.append("# kitty 0.49 removed adjust_line_height; modify_font replaces it")
        kitty.append(f"modify_font cell_height {_pct_arg(line)}")
    if cell:
        kitty.append(f"# cell is {plan['advance_em']:.2f} em; widening to "
                     f"{CONFIG_ANCHORS['cell_em']:.2f} em costs columns")
        kitty.append(f"# modify_font cell_width {_pct_arg(cell)}")
    if plan["has_ligatures"]:
        kitty.append("# disable_ligatures always   # if you dislike operator ligatures")
    if plan["needs_symbol_fallback"]:
        kitty.append("# this design has no powerline icons of its own:")
        kitty.append("# symbol_map U+E0A0-U+E0B3,U+E0B8-U+E0BF Symbols Nerd Font Mono")
    out["kitty"] = "\n".join(kitty)

    ghostty = [f"font-family = {name}", f"font-size = {size}"]
    if plan["bold"] and plan["bold"] != "Bold":
        ghostty.append(f"font-style-bold = {bold}")
    if line:
        ghostty.append(f"adjust-cell-height = {_pct_arg(line)}")
    if cell:
        ghostty.append(f"# cell is {plan['advance_em']:.2f} em; widening costs columns")
        ghostty.append(f"# adjust-cell-width = {_pct_arg(cell)}")
    if plan["has_ligatures"]:
        ghostty.append("font-feature = -calt   # if you dislike operator ligatures")
    if plan["needs_symbol_fallback"]:
        ghostty.append(f"# fallback, for the powerline icons this design lacks:")
        ghostty.append(f"font-family = {plan['symbol_fallback']}")
    ghostty.append("# font-thicken = true  # macOS only; redraws the stroke heavier")
    out["ghostty"] = "\n".join(ghostty)

    lua = ["config.font = wezterm.font_with_fallback({"]

    lua.append(f'  {{ family = "{name}", weight = "{plan["regular"]}" }},')
    if plan["needs_symbol_fallback"]:
        lua.append(f'  "{plan["symbol_fallback"]}",   -- this design has no powerline icons')
    lua.append("})")
    lua.append(f"config.font_size = {size}")
    if line:
        lua.append(f"-- wezterm scales the computed height, so this is the ratio, not the"
                   f" target")
        lua.append(f"config.line_height = {1 + line / 100:.2f}")
    if cell:
        lua.append(f"-- config.cell_width = {1 + cell / 100:.2f}  "
                   f"-- {plan['advance_em']:.2f} to {CONFIG_ANCHORS['cell_em']:.2f} em")
    if plan["has_ligatures"]:
        lua.append('-- config.harfbuzz_features = { "calt=0" }  -- disable ligatures')
    out["wezterm"] = "\n".join(lua)

    toml = ["[font]", f"size = {size}"]
    if line:
        toml.append(f"# alacritty has no line-height option. This face's own default is")
        toml.append(f"# {plan['line_height_em']:.3f} em; the cell height follows the font metrics.")
    toml.append("")
    installed = {"normal": plan["regular"], "bold": plan["bold"],
                 "italic": plan["italic"], "bold_italic": plan["bold_italic"]}
    for section in ("normal", "bold", "italic", "bold_italic"):
        style = installed[section]
        if section != "normal" and not style:
            toml.append(f"# [font.{section}] not installed; alacritty falls back to normal")
            continue
        toml.append(f"[font.{section}]")
        toml.append(f'family = "{name}"')
        toml.append(f'style = "{style}"')
    if plan["needs_symbol_fallback"]:
        toml.append("")
        toml.append("# no powerline icons in this face; alacritty falls back through "
                    "fontconfig")
    out["alacritty"] = "\n".join(toml)

    gui = [f"Regular Font: {name} {plan['regular']}".strip(),
           f"Size: {size:.1f} pt"]
    if plan["line_delta"]:
        change = (plan["line_target"] - plan["line_height_em"]) * size
        gui.append(f'Vertical Spacing: {change:+.1f} pt   (this face ships '
                   f'{plan["line_height_em"]:.3f} em)')
    if plan["bold"]:
        gui.append(f"Bold Font: {name} {bold}   (tick \"Use Bold Font\")")
    if plan["italic"]:
        gui.append(f"Italic Font: {name} {italic}")
    if plan["needs_symbol_fallback"]:
        gui.append(f"Non-ASCII Font: {plan['symbol_fallback']}")
    if plan["has_ligatures"]:
        gui.append("Use Ligatures: your call — no study measures a comprehension benefit")
    out["iTerm2"] = "\n".join(gui)
    return out


def config_section(fonts: list[Family], bands: dict[str, tuple[float, float]],
                   meta: dict[str, Any]) -> str:
    versions = meta.get("terminal_versions") or {}
    midpoint = round((bands["rhythm"][0] + bands["rhythm"][1]) / 2, 2)
    lines = [
        "<p class=\"note\">Which font, at which size, and what to adjust. Every value is",
        "derived from the measurements above: the size puts the measured x-height at",
        f"{CONFIG_ANCHORS['x_height_px']:.1f}&nbsp;px, the cell width pulls a narrow face toward",
        f"{CONFIG_ANCHORS['cell_em']:.2f}&nbsp;em, and the line height moves a face's own default",
        f"toward the middle of the rhythm band, {esc(str(midpoint))}&nbsp;em. Adjustments",
        f"smaller than {CONFIG_ANCHORS['emit_threshold_pct']:.0f}% are omitted as noise.</p>",
        "<p class=\"note\">A font with no line entry needs no line config: its own default "
        "already sits inside the band, and every terminal here derives its cell height from "
        "the font's metrics when nothing overrides it. The entry is absent because there is "
        "nothing to set, not because it was skipped.</p>",
        "<p class=\"note\">Syntax was checked against the version installed here: "
        + ", ".join(f"<code>{esc(name)} {esc(version)}</code>"
                    for name, version in versions.items() if version)
        + ". This matters: kitty dropped <code>adjust_line_height</code> in favour of "
          "<code>modify_font cell_height</code>, so a snippet written from memory breaks.",
        f" {meta.get('size_note', '')}</p>",
    ]
    missing = [family.name for family in fonts if not family.installed]
    if missing:
        lines.append(f"<p class=\"note\">Not installed here, so install before using: "
                     f"{esc(', '.join(missing))}.</p>")
    blocks = []
    for index, family in enumerate(fonts):
        plan = config_plan(family, bands)
        snippets = config_snippets(plan)
        summary_bits = [f"{plan['size']:.1f} pt"]
        if plan["cell_delta"]:
            summary_bits.append(f"cell {_pct(plan['cell_delta'])}")
        if plan["line_delta"]:
            summary_bits.append(f"line {_pct(plan['line_delta'])}")
        figures = []
        for terminal, path, kind in CONFIG_TERMINALS:
            hint = "" if kind != "gui" else " <span class=\"flag\">no text config</span>"
            figures.append(
                f'<figure class="cfg-block"><figcaption>{esc(terminal)} '
                f"<code>{path}</code>{hint}"
                f'<button class="copy" type="button" aria-label="copy {esc(terminal)} '
                f'snippet for {esc(family.name)}">copy</button></figcaption>'
                f'<pre class="cfg">{esc(snippets[terminal])}</pre></figure>')
        blocks.append(
            f'<details class="cfg" id="cfg-{esc(slug(family.name))}"'
            + (" open" if index < 2 else "")
            + f"><summary><code>{esc(family.name)}</code>"
              f'<span class="cfg-meta">{" &middot; ".join(summary_bits)}'
              f" &middot; {esc(plan['size_reason'])}</span></summary>"
              f'<div class="cfg-grid">{"".join(figures)}</div></details>')
    covered = len(fonts)
    lines.append(
        f"<p class=\"note\">{covered} fonts are covered here: the leaders plus the ones "
        f"configured on this machine. Regenerate with "
        f"<code>python3 scripts/font-report.py --config-fonts 0</code> to emit a snippet block "
        f"for every ranked font, or <code>--config-fonts 3</code> for just the top three.</p>")
    index_links = " ".join(
        f'<a href="#cfg-{esc(slug(family.name))}">{esc(family.name)}</a>'
        for family in fonts)
    return ("\n".join(lines) + f'<p class="note">{index_links}</p>' + "".join(blocks))


def inventory_note(meta: dict[str, Any]) -> str:
    inventory = meta.get("inventory") or {}
    if not inventory:
        return ""
    directories = ", ".join(f"<code>{esc(d.replace(os.path.expanduser('~'), '~'))}</code>"
                            for d in inventory.get("directories", []))
    extra = (", plus the download cache for the post-2019 test,"
             if inventory.get("extra_directories") else "")
    return (
        f"Every font file in {directories}{extra} was opened and its printable ASCII advances "
        f"compared: {inventory.get('files_scanned', 0)} files, "
        f"{inventory.get('monospaced_faces', 0)} monospaced faces kept, "
        f"{inventory.get('proportional_faces_skipped', 0)} proportional faces skipped. "
        f"Membership is decided by measuring the font, not by asking fontconfig, which "
        f"reports Monaco's spacing as dual and would drop it from a terminal's chooser "
        f"while the chooser still offers it.")


def chooser_table(ranked: list[Family], all_families: list[Family],
                  meta: dict[str, Any]) -> str:
    """Reconcile the terminal's font chooser against what was measured.

    The chooser list is a snapshot recorded in the meta file: kitty enumerates
    fonts through CoreText and offers no non-interactive way to dump the list, so
    the reconciliation is done by name against a recorded snapshot rather than
    queried live.
    """
    names = meta.get("chooser_families") or []
    if not names:
        return ""
    rank_of = {family.name.lower(): index for index, family in enumerate(ranked, start=1)}
    canonical_of: dict[str, Family] = {}
    for family in all_families:
        canonical_of[family.name.lower()] = family
        for alias in family.aliases:
            canonical_of[alias.lower()] = family
    rows = []
    missing = 0
    for name in names:
        family = canonical_of.get(name.lower())
        if family is None:
            skipped = {entry.lower() for entry in (meta.get("inventory") or {})
                       .get("skipped_families", [])}
            if name.lower() in skipped:
                status = ('<span class="pill mid">not ASCII-monospaced</span>'
                          ' <span class="flag">installed, but its printable ASCII '
                          'advances are not uniform</span>')
            else:
                status = '<span class="pill bad">no font file found</span>'
                missing += 1
        elif family.excluded:
            reason = esc(family.details.get("excluded_reason") or "not a Latin coding face")
            status = f'<span class="pill mid">excluded</span> <span class="flag">{reason}</span>'
        else:
            rank = rank_of.get(family.name.lower())
            status = (f'<span class="pill ok">rank {rank}</span>'
                      if rank else '<span class="pill ok">measured</span>')
            if family.name.lower() != name.lower():
                status += (f' <span class="flag">same design as '
                           f'<code>{esc(family.name)}</code></span>')
        rows.append(f"<tr><td><code>{esc(name)}</code></td><td>{status}</td></tr>")
    note = ("No family the chooser offers is missing from the machine."
            if not missing else
            f"{missing} famil{'y' if missing == 1 else 'ies'} the chooser offers could not be "
            f"located as a font file here at all.")
    return (table("<tr><th>family offered by the terminal</th><th>status here</th></tr>",
                  "".join(rows), "chooser reconciliation", "matrix", "text-align:left")
            + f"<p class='axis-note'>{note}</p>")


def switching_note(ranked: list[Family], names: list[str]) -> str:
    """State the gap to the top of the ranking against the method's noise floor."""
    wanted = {name.lower() for name in names}
    used = [family for family in ranked if family.name.lower() in wanted]
    if not used or not ranked:
        return ""
    leader, best_used = ranked[0], used[0]
    gap = leader.scores["marathon"] - best_used.scores["marathon"]
    if gap < NOISE_POINTS:
        return (f"The best of them is within {NOISE_POINTS:.0f} points of the top of the "
                f"ranking, which is under the noise floor in the method, so nothing here "
                f"argues for switching.")
    return (f"{esc(leader.name)} scores {gap:.1f} points above the best of them, which is over "
            f"the {NOISE_POINTS:.0f}-point noise floor in the method. That is a closer fit to "
            f"declared heuristics, mostly {gap_drivers(leader, best_used)}. It is not evidence "
            f"that switching reduces strain.")


def used_fonts_box(ranked: list[Family], meta: dict[str, Any]) -> str:
    """Say where the fonts already configured on this machine landed.

    The list comes from the meta file, so the generator stays independent of any
    particular config file.
    """
    names = meta.get("used_fonts") or []
    if not names:
        return ""
    by_name = {family.name.lower(): (index, family)
               for index, family in enumerate(ranked, start=1)}
    rows = []
    for name in names:
        found = by_name.get(name.lower())
        if not found:
            rows.append(f'<li><code>{esc(name)}</code> &mdash; not installed, or not '
                        f'a monospaced family on this machine.</li>')
            continue
        index, family = found
        light = family.weight_for("light")
        dark = family.weight_for("dark")
        rows.append(
            f'<li><code>{esc(name)}</code> &mdash; rank {index} of {len(ranked)} '
            f'at {family.scores.get("marathon", 0):.1f}, '
            f'x-height {family.vertical.get("x_height_em", 0):.3f} em, closest pair '
            f'{nearest_pair_note(family)}, weights for light and dark '
            f'{esc((light or {}).get("subfamily", "&mdash;"))} and '
            f'{esc((dark or {}).get("subfamily", "&mdash;"))}.</li>')
    return ('<div class="callout"><b>Where the fonts already configured here landed.</b>'
            '<ul class="method">' + "".join(rows) + "</ul>"
            f'<p class="note">{switching_note(ranked, names)}</p></div>')


def source_label(row: dict[str, Any]) -> str:
    if row["source"] == "cask":
        return f"full release ({esc(row.get('version') or 'cask')})"
    if row["source"] == "webfont":
        return "catalogue webfont"
    return "&mdash;"


def status_of(row: dict[str, Any], family: Family | None, rank: int | None) -> str:
    if row["status"] != "fetched":
        return esc(row["status"])
    if family is None:
        return "fetched, but no face has uniform printable ASCII advances"
    if rank is None:
        return esc(family.details.get("excluded_reason") or "excluded")
    if family.installed:
        return f"installed as {esc(family.name)}, scored from that copy"
    if family.installed_sibling:
        return f"older or patched build installed as {esc(family.installed_sibling)}"
    return "not installed"


def recent_rows(ranked: list[Family], families: list[Family],
                manifest: dict[str, Any]) -> list[tuple[dict[str, Any], Family | None, int | None]]:
    """Every catalogue row, ranked ones first, so nothing selected goes unreported."""
    rank_of = {id(family): index for index, family in enumerate(ranked, start=1)}
    owner = {row["key"]: family for family in families for row in family.recent}
    rows = []
    for row in manifest["fonts"]:
        family = owner.get(row["key"])
        rows.append((row, family, rank_of.get(id(family)) if family else None))
    rows.sort(key=lambda item: (item[2] is None, item[2] or 0, -item[0]["year"], item[0]["name"]))
    return rows


def recent_table(rows: list[tuple[dict[str, Any], Family | None, int | None]]) -> str:
    body = []
    for row, family, rank in rows:
        name = esc(row["name"])
        if family is not None and rank is not None:
            name = f'<a href="#{esc(slug(family.name))}"><code>{name}</code></a>'
            scored = [
                f'<td class="num">{rank}</td>',
                f'<td>{name}</td>',
                f'<td class="num">{row["year"]}</td>',
                f'<td>{esc(row.get("license") or "")}</td>',
                f'<td>{source_label(row)}</td>',
                f'<td class="num">{len(family.faces)}</td>',
                f'<td class="num">{len(family.upright_weights)}</td>',
                f'<td class="num strong">{family.scores.get("marathon", 0):.1f}</td>',
                f'<td class="num">{family.scores.get("density_first", 0):.1f}</td>',
                f'<td class="num"{sort_attr(worst_pair_distance(family))}>'
                f'{closest_pair_cell(family)}</td>',
                f'<td>{esc(family.disambiguation.get("zero_style") or "plain")}</td>',
            ]
        else:
            scored = [
                '<td class="num">&mdash;</td>',
                f'<td><code>{name}</code></td>',
                f'<td class="num">{row["year"]}</td>',
                f'<td>{esc(row.get("license") or "")}</td>',
                f'<td>{source_label(row)}</td>',
            ] + ['<td class="num">&mdash;</td>'] * 5 + ['<td>&mdash;</td>']
        status = status_of(row, family, rank)
        body.append(f'<tr>{"".join(scored)}<td class="flag">{status}</td></tr>')
    header = ('<tr><th class="num">rank</th><th>font</th><th class="num">year</th><th>licence</th>'
              '<th>source</th><th class="num">faces</th><th class="num">upright<br>weights</th>'
              '<th class="num">long-<br>session</th><th class="num">density-<br>first</th>'
              '<th class="num">worst<br>pair</th><th>zero</th><th>status</th></tr>')
    return table(header, "".join(body), "recent releases", "board sortable")


# Every valid @font-face weight and style, and nothing that can leave the declaration.
_CSS_WEIGHT_NUMBER = r"(?:1000|[1-9]\d{0,2}(?:\.\d+)?)"
CSS_WEIGHT = re.compile(rf"normal|bold|{_CSS_WEIGHT_NUMBER}(?: +{_CSS_WEIGHT_NUMBER})?")
CSS_STYLE = re.compile(r"normal|italic|oblique(?: +-?\d{1,2}(?:\.\d+)?deg){0,2}")


def css_string(text: str) -> str:
    """Text safe inside a double-quoted CSS string in a <style> element.

    Catalogue names come from a third party, so quotes, backslashes, angle brackets
    and line breaks become CSS escapes and cannot close the string or the element.
    """
    return re.sub(r'["\\<>\n\r\f]', lambda match: f"\\{ord(match.group()):x} ", text)


def recent_font_faces(families: list[Family]) -> str:
    """Load uninstalled designs from files beside the report so their previews are real.

    The hosted report's CSP allows fonts only from its own origin, so the urls are relative.
    local() comes first, so a reader who has the font uses their own copy. A face with no
    `file` was not served, and only that local copy can show it.
    """
    rules = []
    for family in families:
        if family.installed or not family.recent:
            continue
        name = css_string(family.name)
        local = css_string(family.font_family or family.name)
        for face in family.recent[0].get("webfont_faces") or []:
            if not (CSS_WEIGHT.fullmatch(face["weight"]) and CSS_STYLE.fullmatch(face["style"])):
                continue
            served = f',url("{face["file"]}") format("woff2")' if face.get("file") else ""
            rules.append(
                f'@font-face{{font-family:"{name}";font-weight:{face["weight"]};'
                f'font-style:{face["style"]};font-display:swap;'
                f'src:local("{local}"){served}}}')
    return "\n".join(rules)


def webfont_note(control: dict[str, Any] | None) -> str:
    if not control:
        return ("Webfont rows carry at most four faces, and how far that moves a score was "
                "not sized in this run, so do not read them as equal to full releases.")
    return (
        f"<b>Webfont rows are not equal to full-release rows.</b> The {control['fonts']} fonts "
        f"available both ways were measured both ways: the full release scored a median "
        f"{control['median']:+.1f} points against its own webfont, ranging "
        f"{control['min']:+.1f} to {control['max']:+.1f}, and {control['over_threshold']} moved "
        f"by more than {control['threshold']:.0f}. The median gain from the weight axis alone is "
        f"{control['weights_median']:+.1f}, because a webfont stops at four faces. A webfont can "
        f"also be an older build than the release, which is why some move down. Read a webfont "
        f"row as a provisional score, not a verdict.")


def gap_drivers(leader: Family, other: Family, count: int = 2) -> str:
    """The axes that contribute most to one font's lead over another, in points."""
    contributions = sorted(
        ((axis, weight * (leader.scores.get(axis, 0) - other.scores.get(axis, 0)))
         for axis, weight in MARATHON_WEIGHTS.items()), key=lambda item: -item[1])
    return " and ".join(f"{esc(AXIS_LABELS[axis])} ({points:+.1f})"
                        for axis, points in contributions[:count])


def recent_section(ranked: list[Family], families: list[Family], manifest: dict[str, Any],
                   meta: dict[str, Any]) -> str:
    if not manifest:
        return ""
    rows = recent_rows(ranked, families, manifest)
    tested = [item for item in rows if item[2] is not None]
    skipped = [item for item in rows if item[0]["status"].startswith("skipped")]
    failed = [item for item in rows if item[0]["status"].startswith("failed")]
    unranked = [item for item in rows if item[2] is None and item[0]["status"] == "fetched"]
    designs = {id(item[1]) for item in tested}
    new = [family for family in ranked
           if family.recent and not family.installed and not family.installed_sibling]
    best_new = new[0] if new else None
    best_installed = next((family for family in ranked if family.installed), None)
    catalogue = manifest["catalogue"]
    commit = catalogue["repo_commit"]
    outcome = []
    if best_new and best_installed:
        ahead = (best_new.scores["marathon"] - best_installed.scores["marathon"])
        outcome.append(
            f'<p><strong>Best font not installed here: {esc(best_new.name)} '
            f'({best_new.scores["marathon"]:.1f}, rank {ranked.index(best_new) + 1}). '
            f'Best installed: {esc(best_installed.name)} '
            f'({best_installed.scores["marathon"]:.1f}, rank '
            f'{ranked.index(best_installed) + 1}).</strong> '
            f'The gap is {ahead:+.1f} points on declared heuristic weights, mostly from '
            f'{gap_drivers(best_new, best_installed)}. It shows a closer fit to these axes, '
            f'not less eye strain.</p>')
    return f"""<h2>Fonts released after {manifest["cutoff_year"]}</h2>
<p class="note">The <a href="{esc(catalogue["url"])}">programmingfonts.org</a> catalogue
lists {catalogue["entries"]} fonts at commit <code>{esc(commit[:7])}</code>, read on
{esc(catalogue["fetched"])}. {len(rows)} carry a release year after {manifest["cutoff_year"]}.
{len(tested)} of those were measured and ranked above, as {len(designs)} designs on the same
scales as everything else. {len(skipped)} are commercial and were not downloaded,
{len(unranked)} fetched but did not qualify, and {len(failed)} failed to download. The year is the catalogue's,
so a reissue or a later release of an older design keeps whatever the catalogue states.</p>
{"".join(outcome)}
{recent_table(rows)}
<p class="note">Nothing here was installed: files sit in a gitignored cache read only by the
measurement. A <i>full release</i> comes from the Homebrew cask's upstream archive. A
<i>catalogue webfont</i> is what programmingfonts.org serves, used when no cask exists.
{webfont_note(meta.get("webfont_control"))}</p>
"""


def evidence_table() -> str:
    rows = []
    for axis in RADAR_AXES:
        status, note = EVIDENCE[axis]
        css = {"supported": "ok", "trade-off": "bad"}.get(status, "mid")
        rows.append(f'<tr><td><code>{esc(axis)}</code><br>'
                    f'<span class="note">{esc(AXIS_LABELS[axis])}</span></td>'
                    f'<td><span class="pill {css}">{esc(status)}</span></td>'
                    f'<td>{note}</td></tr>')
    return table("<tr><th>axis</th><th>status</th><th>basis</th></tr>",
                 "".join(rows), "evidence table", "matrix", "text-align:left")


def polarity_table(families: list[Family]) -> str:
    rows = []
    for family in families:
        light = family.weight_for("light")
        dark = family.weight_for("dark")
        def cell(item: dict[str, Any] | None) -> str:
            if not item:
                return "&mdash;"
            name = item["subfamily"] or str(item["weight_class"])
            flag = "" if item["in_band"] else ' <span class="flag">outside band</span>'
            return f"<code>{esc(name)}</code> <span class=\"dimtxt\">{item['stem_em']:.3f}</span>{flag}"
        same = (light and dark and light["weight_class"] == dark["weight_class"])
        if same:
            if light and light["in_band"]:
                verdict = "one weight serves both"
            elif light:
                verdict = "one weight, outside both bands"
            else:
                verdict = "unmeasured"
        elif len(family.upright_weights) == 1:
            verdict = "family has one weight only"
        else:
            verdict = "step up for dark"
        rows.append(
            f'<tr><td><a href="#{esc(slug(family.name))}"><code>{esc(family.name)}</code></a></td>'
            f"<td{sort_attr(light and light['stem_em'])}>{cell(light)}</td>"
            f"<td{sort_attr(dark and dark['stem_em'])}>{cell(dark)}</td>"
            f"<td>{esc(verdict)}</td></tr>")
    return table("<tr><th>font</th><th>light mode (dark ink on light paper)</th>"
                 "<th>dark mode (light ink on dark paper)</th><th>verdict</th></tr>",
                 "".join(rows), "polarity table", "matrix weights-table sortable")


# --------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------

PREVIEW_PX = 13
PREVIEW_OPEN = 12


class Span(NamedTuple):
    text: str
    role: str
    face: str = "regular"


FACE_CSS = {
    "regular": "",
    "bold": "font-weight:700",
    "italic": "font-style:italic",
    "bold italic": "font-weight:700;font-style:italic",
}
FACE_SAMPLE = "def f(0O, 1lI) -> ag != qy"

# The session carries the confusable glyphs the distinction axis measures and the rule
# glyphs the furniture axis measures. Bold keywords and italic comments match how themes
# commonly use those faces.
PREVIEW_LINES: list[list[Span]] = [
    [Span("noomz@mbp", "str"), Span(" ", "fg"), Span("~/P/noomz-themes", "key")],
    [Span("\u276f", "dim"), Span(' rg -n "rn m cl d" scripts/ | head -2', "fg")],
    [Span("scripts/font-report.py", "num"), Span(":", "dim"), Span("351", "key"),
     Span(": 0O 1lI| 5S 2Z 8B gq9 ;:, vv w ii u", "fg")],
    [Span("def ", "key", "bold"), Span('rank(faces, axis="distinction"):', "fg")],
    [Span("    # measured, not asserted", "com", "italic")],
    [Span("    return ", "key", "bold"), Span("sorted(s, key=lambda p: -p[1])", "fg")],
    [Span("id", "fg"), Span(" = ", "dim"), Span("0x4F1A", "num"), Span("  ", "fg"),
     Span("a != b <= c -> d", "fg")],
    [Span("\u250c\u2500 build \u2500\u2500\u2500\u252c\u2500 tests \u2500\u2500\u2500\u2510", "dim")],
    [Span("\u2502 ", "dim"), Span("ok", "str"), Span(" 12s    \u2502 ", "dim"), Span("41/41", "str"),
     Span("     \u2502", "dim")],
    [Span("\u2514" + "\u2500" * 11 + "\u2534" + "\u2500" * 11 + "\u2518", "dim")],
    [Span("\u2588\u2593\u2592\u2591 ", "num"), Span("warning", "num"), Span(" ", "fg"),
     Span("3 files changed", "dim")],
]


def palette(name: str) -> dict[str, str]:
    """Pull a shipped palette out of themes/ so both reports agree."""
    path = os.path.join("themes", "claude", f"{name}.json")
    colours: dict[str, str] = {}
    try:
        with open(path) as handle:
            data = json.load(handle)
        overrides = data.get("overrides", data)
        # base can be a variant such as light-daltonized; a light one uses the palette
        # report's canvas as its background
        colours["bg"] = "#fcf7ed" if str(data.get("base")).startswith("light") else "#1e1e2e"
        colours["fg"] = overrides.get("text", colours["bg"])
        colours["dim"] = overrides.get("inactive", colours["fg"])
        colours["comment"] = overrides.get("subtle", colours["dim"])
        colours["key"] = overrides.get("claude", colours["fg"])
        colours["str"] = overrides.get("success", colours["fg"])
        colours["num"] = overrides.get("warning", colours["fg"])
        colours["func"] = overrides.get("ide", colours["fg"])
    except (OSError, ValueError):
        colours = {"bg": "#ffffff", "fg": "#000000", "dim": "#595959",
                   "comment": "#595959", "key": "#721045", "str": "#006800",
                   "num": "#6f5500", "func": "#0031a9"}
    return colours


def specimen_css(colours: dict[str, str], polarity: str) -> str:
    return (f'.{polarity}{{--spec-bg:{colours["bg"]};'
            f'--syn-fg:{colours["fg"]};--syn-dim:{colours["dim"]};'
            f'--syn-com:{colours["comment"]};--syn-key:{colours["key"]};'
            f'--syn-str:{colours["str"]};--syn-num:{colours["num"]};}}')


def build_document(families: list[Family], bands: dict[str, tuple[float, float]],
                   css: str, meta: dict[str, Any]) -> str:
    ranked = [f for f in families if not f.excluded]
    # The reference table is for installed faces that are not candidates but are
    # still fonts someone might wonder about: legacy and hidden system families.
    # Icon fonts are left out entirely — a score computed from these axes says
    # nothing useful about a collection of symbols.
    reference = [f for f in families if f.excluded
                 and (f.vertical.get("ascii_coverage") or 0) > 0.95
                 and not f.name.startswith(".")]
    ranked.sort(key=lambda f: -f.scores.get("marathon", 0))
    reference.sort(key=lambda f: -f.scores.get("marathon", 0))

    top = ranked[0] if ranked else None
    density_top = max(ranked, key=lambda f: f.scores.get("density_first", 0)) if ranked else None
    second = ranked[1] if len(ranked) > 1 else None

    light_palette = palette("modus-operandi")
    dark_palette = palette("catppuccin-mocha")

    radar_series = []
    colours = ["#8a2b1f", "#1a6b2f", "#8a6b00", "#0031a9", "#721045",
               "#005e8b", "#7a5c2e", "#3f3f3f"]
    for index, family in enumerate(ranked[:8]):
        radar_series.append((family.name, colours[index % len(colours)], family.scores))

    wanted = {name.lower() for name in (meta.get("used_fonts") or [])}
    limit = meta.get("config_fonts_limit", 12)
    config_fonts = [family for family in ranked if family.name.lower() in wanted]
    for family in ranked:
        if family not in config_fonts:
            config_fonts.append(family)
    config_fonts = config_fonts if limit in (0, None) else config_fonts[:limit]

    medals = ["#1", "#2", "#3"]
    top_lines = []
    for index, family in enumerate(ranked[:3]):
        light = family.weight_for("light")
        dark = family.weight_for("dark")

        def band(item: dict[str, Any] | None) -> str:
            if not item:
                return "&mdash;"
            name = esc(item["subfamily"] or item["weight_class"])
            return f"{name} {item['stem_em']:.3f}&nbsp;em" + (
                "" if item["in_band"] else " (outside the declared band)")

        top_lines.append(
            f"<li><b>{medals[index]} {esc(family.name)} &mdash; "
            f"{family.scores.get('marathon', 0):.1f}</b>{recent_marker(family)}. "
            f"x-height {family.vertical.get('x_height_em', 0):.3f} em, closest pair "
            f"{nearest_pair_note(family)}, zero "
            f"{esc(family.disambiguation.get('zero_style') or 'plain')}, "
            f"stroke contrast {get(family.stroke, 'contrast', default=0):.2f}:1, "
            f"{len(family.upright_weights)} upright weights. "
            f"Light mode &rarr; {band(light)}, dark mode &rarr; {band(dark)}.</li>")

    reference_note = ("Rows below the divider are installed faces that are not "
                      "candidate coding fonts; they are scored with the same formulas "
                      "for reference."
                      if reference else
                      "Every installed face that is not an icon font is ranked; there "
                      "is no separate reference table.")
    band_notes = [
        f"<b>declared</b> x-height anchors {bands['x_height'][0]:.2f} em &rarr; 0 and "
        f"{bands['x_height'][1]:.2f} em &rarr; 100; measured spread was "
        f"{bands['x_height_observed'][0]:.3f}&ndash;{bands['x_height_observed'][1]:.3f} em",
        f"<b>declared</b> stroke-contrast anchors {bands['contrast'][0]:.2f}:1 &rarr; 0 and "
        f"{bands['contrast'][1]:.2f}:1 &rarr; 100; measured spread was "
        f"{bands['contrast_observed'][0]:.2f}&ndash;{bands['contrast_observed'][1]:.2f}:1",
        "<b>declared</b> distinction is scored by subtraction, not by a scale: "
        f"&minus;{DEDUCTION['no_marked_zero']} when the zero carries no mark, "
        f"&minus;{DEDUCTION['no_one_family_cue']} when the 1/l/I set carries fewer than "
        f"two cues between them, &minus;{DEDUCTION['pair_critical_close']} for each pair on "
        f"the code-critical list and &minus;{DEDUCTION['pair_close']} for each other pair "
        f"measuring below {CLOSE_FLOOR:.2f} that nothing resolves. "
        f"Closest measured pairs over the installed set run {bands['confusion'][0]:.3f} to "
        f"{bands['confusion'][1]:.3f}.",
        f"<b>observed</b> columns per 1000 px {bands['cols'][0]:.1f} &rarr; 0 and "
        f"{bands['cols'][1]:.1f} &rarr; 100 (5th&ndash;95th percentile)",
        f"<b>band</b> ink density {bands['density'][0]:.4f}&ndash;{bands['density'][1]:.4f} of the "
        f"cell scores 100, falling to 0 at {bands['density'][2]:.4f} and {bands['density'][3]:.4f}",
        f"<b>band</b> default line height {bands['rhythm'][0]:.2f}&ndash;{bands['rhythm'][1]:.2f} em "
        f"scores 100, falling to 0 at {bands['rhythm'][2]:.2f} and {bands['rhythm'][3]:.2f} em",
    ]

    method_points = meta.get("method_points", [])
    sources = meta.get("sources", [])
    not_measured = meta.get("not_measured", [])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Typeface evaluation: monospace fonts for long sessions</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{css}
{EXTRA_CSS}
{specimen_css(light_palette, "light")}
{specimen_css(dark_palette, "dark")}
{recent_font_faces(families)}
</style></head><body><div class="wrap">

<h1>Typeface evaluation for long working sessions</h1>
<p class="sub">Measured from font binaries on this machine, installed or downloaded for this test: {len(ranked)} designs,
{meta.get('face_count', 0)} faces, outlines via fontTools and rasterisation via FreeType.
Generated by <code>scripts/font-report.py</code> from <code>docs/font-metrics.json</code>.</p>
<p class="note">{inventory_note(meta)}</p>

<div class="verdict">
<p><strong>Long-session ranking: {esc(top.name) if top else "&mdash;"}
({top.scores.get('marathon', 0) if top else 0:.1f}).</strong>
{esc(second.name) if second else ""}
takes second at {second.scores.get('marathon', 0) if second else 0:.1f}, and the
density-first viewpoint promotes {esc(density_top.name) if density_top else "&mdash;"}
({density_top.scores.get('density_first', 0) if density_top else 0:.1f}) instead &mdash;
the same measurement set read for screen real estate rather than for wear.</p>
<ol class="method">{''.join(top_lines)}</ol>
<p><strong>The ranking is a measurement, not a comfort guarantee.</strong>
No study ranks typefaces by eye strain, and this one does not either. What is
measured here is how far apart the ambiguous glyphs are at reading size, how much
ink a screenful of code lays down, how much room a typeface gives small text, and
which weight suits each polarity. Those are proxies for decoding effort.</p>
<p class="note">{meta.get('verdict_note', '')}</p>
</div>

<div class="callout">{meta.get('lead_finding', '')}</div>

{used_fonts_box(ranked, meta)}

<h2>Leaderboard</h2>
<p class="note">Two weightings, one set of measurements. <b>Long-session</b> is the ranking
used in this document: glyph distinction .22, x-height .16, weight range .12, optical
density .14, line spacing .10, monolinearity .10, terminal furniture .10, rendering .06.
<b>Density-first</b> is the screen-real-estate view: columns per screen .28, x-height .18,
density .16, distinction .14, spacing .08, monolinearity .06, weights .06, rendering .02,
furniture .02. The delta column is long-session minus density-first, so a positive number
means the font gains when wear matters more than columns.</p>
<p class="note">Every axis is a declared heuristic computed from the numbers in
<code>docs/font-metrics.json</code>, and every band it uses is listed under
<i>Bands and anchors</i>. <code>worst pair</code> is the smallest symmetric
difference over the union of two glyph masks at design size &mdash; lower is more
confusable. A <span class="flag">cue</span> marker means the pair measures close but a
deliberate glyph cue keeps it apart anyway, so it is not charged against the font.
{reference_note}</p>

{leaderboard(ranked, "Long-session leaderboard",
             "Ranked by long-session score. Higher is better on every column except "
             "<i>worst pair</i>, <i>stroke contrast</i> and <i>line height</i>, where the "
             "axes are read against the bands in the method.", bands,
             (meta.get("recent_fonts") or {}).get("cutoff_year"), reference)}

{recent_section(ranked, families, meta.get("recent_fonts") or {}, meta)}

{preview_section(ranked, light_palette, dark_palette)}

<h2>Which weight, and for which polarity</h2>
<div class="callout warn"><b>This section is convention, not evidence.</b>
The claim that dark mode wants a heavier stroke than light mode is repeated widely in
design guidance, and the reviewed literature does not establish it: the bloom or
halation mechanism is not even named in the two most relevant reviews, and Dobres et al.
(2016) found no typeface &times; polarity interaction at all &mdash; one ranking of faces
held in both polarities. What follows is therefore a recommendation you are free to
ignore, sitting on top of a measurement you are not: the stem width of every measured
weight, per family.</div>
<p class="note">The declared bands are 0.070&ndash;0.090&nbsp;em of stem for light mode and
0.090&ndash;0.112&nbsp;em for dark mode, and the recommendation is the measured weight
whose measured stem lands nearest the middle of the band. Where a family has no weight in
the band, the nearest weight is named and flagged &mdash; a two-weight family has only
Regular and Bold to offer, and that jump is usually larger than the band asked for.</p>
{polarity_table(ranked)}

<h2>Ready-to-copy config</h2>
{config_section(config_fonts, bands, meta)}

<h2>What the font chooser offers, and where each face is</h2>
<p class="note">Reconciled against the list the terminal's font picker shows on this
machine. A chooser lists what its font engine believes is monospaced, which is the same
property the inventory is built on, so the two should agree &mdash; and where they differ,
the difference is stated rather than hidden.</p>
{chooser_table(ranked, families, meta)}

<h2>Ambiguity, per font</h2>
<p class="note">The sets that cost a developer real time, and whether the face resolves
them by a deliberate cue rather than by silhouette. Ordered by the closest measured pair,
most confusable first. Numeric cells are the measured symmetric-difference distance for
that pair: below 0.18 is a problem, 0.18&ndash;0.29 is workable, above that the shapes are
clearly apart.</p>
{matrix_table(ranked)}

<h2>Profiles</h2>
<p class="note">The top eight designs on the axes that feed the score, 0&ndash;100.
Hover or focus a legend row to isolate it.</p>
<div class="grid">
<div class="chart">{radar_svg(radar_series, "Top eight designs, eight axes")}</div>
<div>
<p class="note">Reading the shape: a wide, round polygon is a face that gives up
nothing, but the axes are not equally load-bearing. <b>Glyph distinction saturates at
100 for every design in the top eight</b> &mdash; among the coding fonts measured here it is a
solved problem, and on this evidence it separates only the legacy faces, so use it as a
filter rather than as a ranking. X-height carries the most weight after it, and density,
spacing and monolinearity are bands: the middle is best and both ends are worse, so a
font can lose points for being too light as well as too heavy.</p>
<p class="note">Weight range is the axis most often overlooked. A family that ships one
weight cannot be tuned at all, and it is the axis on which the otherwise excellent
Hack build here loses the most.</p>
</div>
</div>

<h2>Details by font</h2>
<div class="cards">
{''.join(card_html(family, index) for index, family in enumerate(ranked, start=1))}
</div>

<h2>What each axis rests on</h2>
<p class="note">The evidence status of every axis, stated next to the axis rather than
implied by the ranking. One of these axes measures robustness rather than comfort
(<code>rendering</code>), one measures a capability you may or may not want
(<code>weights</code>), and one measures a trade-off that costs legibility
(<code>compact</code>, used only in the density-first view).</p>
{evidence_table()}

<h2>Method, and what this does not measure</h2>
<ul class="method">
{''.join(f'<li>{point}</li>' for point in method_points)}
</ul>

<h3>Bands and anchors</h3>
<p class="note">Every axis is a scale or a band. A <b>declared</b> anchor is placed
by hand because the literature gives the direction but not the number; an
<b>observed</b> band comes from the 5th&ndash;95th percentile of the installed fonts, so it
ranks against that set rather than certifying anything, and a font under test cannot move
the scale it is read on.</p>
<ul class="method">
{''.join(f'<li>{point}</li>' for point in band_notes)}
</ul>

<h2>Sources</h2>
<ul class="method">
{''.join(f'<li>{item}</li>' for item in sources)}
</ul>

<footer>Generated by <code>scripts/font-report.py</code> from
<code>docs/font-metrics.json</code>, produced by <code>scripts/font-metrics.py</code>.
Measurements describe the font files on this machine, at the rasterisation
sizes stated in the method, under FreeType and Pillow &mdash; a different rasteriser,
hinting setting or subpixel arrangement shifts the last decimal. Re-run both scripts
after installing or updating a font.</footer>
</div>
<script>
(function(){{
    Array.prototype.forEach.call(
      document.querySelectorAll('button.copy'),
      function(button){{
        button.addEventListener('click', function(){{
          var pre = button.closest('figure').querySelector('pre');
          var text = pre ? pre.textContent : '';
          function done(){{
            button.classList.add('done');
            button.textContent = 'copied';
            window.setTimeout(function(){{
              button.classList.remove('done');
              button.textContent = 'copy';
            }}, 1400);
          }}
          function selectInstead(){{
            // clipboard access can be refused; leave the text selected so Cmd+C works
            var range = document.createRange();
            range.selectNodeContents(pre);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            button.classList.add('done');
            button.textContent = 'press \u2318C';
            window.setTimeout(function(){{
              button.classList.remove('done');
              button.textContent = 'copy';
            }}, 2600);
          }}
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(text).then(done, selectInstead);
          }} else {{
            selectInstead();
          }}
        }});
      }});
  var probe = document.createElement('canvas').getContext('2d');
  function width(stack){{
    probe.font = '72px ' + stack;
    return probe.measureText('mmmwwwiil0O1').width;
  }}
  Array.prototype.forEach.call(document.querySelectorAll('figure[data-font]'), function(figure){{
    var name = '"' + figure.getAttribute('data-font') + '"';
    function check(){{
      // a missing font leaves both stacks at their generic fallback's width
      var missing = width(name + ', monospace') === width('monospace')
        && width(name + ', serif') === width('serif');
      figure.querySelector('.preview-missing').hidden = !missing;
    }}
    document.fonts.load('13px ' + name).then(check, check);
  }});
  var charts = document.querySelectorAll('.chart');
  Array.prototype.forEach.call(charts, function(chart){{
    var svg = chart.querySelector('svg.radar');
    if (!svg) {{ return; }}
    var polys = svg.querySelectorAll('polygon[data-series]');
    function isolate(idx){{
      svg.classList.add('isolating');
      Array.prototype.forEach.call(polys, function(p){{
        p.classList.toggle('hot', p.getAttribute('data-series') === idx);
      }});
    }}
    function restore(){{
      svg.classList.remove('isolating');
      Array.prototype.forEach.call(polys, function(p){{ p.classList.remove('hot'); }});
    }}
  Array.prototype.forEach.call(
      chart.querySelectorAll('.legend li[data-series]'),
      function(row){{
        var idx = row.getAttribute('data-series');
        row.addEventListener('mouseenter', function(){{ isolate(idx); }});
        row.addEventListener('mouseleave', restore);
        row.addEventListener('focus', function(){{ isolate(idx); }});
        row.addEventListener('blur', restore);
      }});
  }});
}})();
</script>
<script>{BOARD_JS}</script></body></html>
"""


def score_all(families: list[Family], bands: dict[str, tuple[float, float]]) -> None:
    for family in families:
        score_family(family, bands)
        family.scores["marathon"] = composite(family.scores, MARATHON_WEIGHTS)
        family.scores["density_first"] = composite(family.scores, DENSITY_WEIGHTS)


def write_webfont_control(families: list[Family], bands: dict[str, tuple[float, float]],
                          control_dir: str, out: str) -> None:
    """Size how far catalogue webfonts move a score, on the report's own scale.

    control_dir holds a run of fetch-recent-fonts.py --prefer webfont and of
    font-metrics.py over its cache, for fonts the main run measured from a full release.
    """
    with open(os.path.join(control_dir, "font-metrics.json")) as handle:
        records = json.load(handle)
    with open(os.path.join(control_dir, "recent-fonts.json")) as handle:
        manifest = json.load(handle)
    control = build_families(records, cache_root_of(manifest))
    attach_recent(control, manifest)
    score_all(control, bands)
    webfont = {row["key"]: family for family in control if not family.installed
               for row in family.recent}
    moves, weight_moves = [], []
    for family in families:
        if family.installed:
            continue
        for row in family.recent:
            other = webfont.get(row["key"])
            if row["source"] == "cask" and other is not None:
                moves.append(family.scores["marathon"] - other.scores["marathon"])
                weight_moves.append(MARATHON_WEIGHTS["weights"]
                                    * (family.scores["weights"] - other.scores["weights"]))
    threshold = 2.0
    summary = {
        "fonts": len(moves), "median": round(statistics.median(moves), 1),
        "min": round(min(moves), 1), "max": round(max(moves), 1), "threshold": threshold,
        "over_threshold": sum(abs(move) > threshold for move in moves),
        "weights_median": round(statistics.median(weight_moves), 1),
    }
    with open(out, "w") as handle:
        json.dump(summary, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(f"wrote {out}: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="docs/font-metrics.json")
    parser.add_argument("--out", default="docs/font-report.html")
    parser.add_argument("--config-fonts", type=int, default=12,
                        help="how many fonts get a ready-to-copy config block (0 = all)")
    parser.add_argument("--meta", default="scripts/font-report-meta.json",
                        help="JSON with verdict_note, lead_finding, method_points, sources")
    parser.add_argument("--recent", default="docs/recent-fonts.json",
                        help="manifest written by fetch-recent-fonts.py")
    parser.add_argument("--control-out", default="docs/recent-fonts-control.json")
    parser.add_argument("--write-control", metavar="DIR",
                        help="size webfont bias from a --prefer webfont run in DIR, then exit")
    args = parser.parse_args()

    with open(args.metrics) as handle:
        records = json.load(handle)
    meta: dict[str, Any] = {"face_count": len(records),
                            "config_fonts_limit": args.config_fonts}
    if os.path.exists(args.meta):
        with open(args.meta) as handle:
            meta.update(json.load(handle))
    inventory_path = os.path.join(os.path.dirname(args.metrics), "font-inventory.json")
    if os.path.exists(inventory_path):
        with open(inventory_path) as handle:
            meta["inventory"] = json.load(handle)
    else:
        print(f"note: {inventory_path} missing, the header will omit inventory counts")

    manifest: dict[str, Any] = {}
    if os.path.exists(args.recent):
        with open(args.recent) as handle:
            manifest = json.load(handle)
        meta["recent_fonts"] = manifest
    families = build_families(records, cache_root_of(manifest) if manifest else "")
    if manifest:
        attach_recent(families, manifest)
    # The scale comes from the installed set, so a font under test cannot move it.
    bands = compute_bands([f for f in families if not f.excluded and f.installed])
    score_all(families, bands)
    if args.write_control:
        write_webfont_control(families, bands, args.write_control, args.control_out)
        return
    if os.path.exists(args.control_out):
        with open(args.control_out) as handle:
            meta["webfont_control"] = json.load(handle)

    css = base_css("docs/palette-report.html")
    document = build_document(families, bands, css, meta)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as handle:
        handle.write(document)
    ranked = sorted([f for f in families if not f.excluded],
                    key=lambda f: -f.scores["marathon"])
    print(f"wrote {args.out}: {len(ranked)} ranked designs, "
          f"{len([f for f in families if f.excluded])} reference/other")
    for family in ranked[:12]:
        print(f"  {family.scores['marathon']:5.1f}  {family.name}")


if __name__ == "__main__":
    main()
