#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools", "brotli"]
# ///
"""Download the programmingfonts.org fonts released after CUTOFF_YEAR for measuring.

Nothing is installed. Files land in a gitignored cache that only font-metrics.py
reads, through --extra-fonts, so the terminal's font list stays as it was.

docs/recent-fonts.json gets one row per catalogue entry, including the ones not
tested, so the report can say what was left out and why.

The catalogue's webfonts also go in docs/fonts, for the report's previews.
--webfonts-only refreshes just those from the existing manifest.

Run with: uv run scripts/fetch-recent-fonts.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

CUTOFF_YEAR = 2019
SITE = "https://www.programmingfonts.org"
REPO = "https://github.com/braver/programmingfonts"
RAW = "https://raw.githubusercontent.com/braver/programmingfonts"
REPORT_DIR = "docs"
CATALOGUE_KEY = re.compile(r"[A-Za-z0-9][\w.-]*")
WEBFONT_URL = re.compile(
    re.escape(SITE) + r"/fonts/resources/([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*\.woff2)")
# artifact-host takes one 32 MiB tar per publish and every font comes to about 37 MiB.
# Only Cilantro Code Mono's two files pass this, and without them the site fits.
MAX_SERVED_BYTES = 5 * 2 ** 19

# Catalogue key -> Homebrew cask and, where one archive holds several catalogue
# entries or proportional siblings, a filename pattern selecting this entry.
# A cask ships the full upstream release. The catalogue's webfonts stop at four faces.
CASKS: dict[str, tuple[str, str | None]] = {
    "adwaita-mono": ("font-adwaita", r"AdwaitaMono"),
    "annotation-mono": ("font-annotation-mono", None),
    "aporetic-sans": ("font-aporetic", r"aporetic-sans-mono"),
    "aporetic-serif": ("font-aporetic", r"aporetic-serif-mono"),
    "atkinson-hyperlegible": ("font-atkinson-hyperlegible-mono", None),
    "azeret": ("font-azeret-mono", None),
    "chivo": ("font-chivo-mono", None),
    "commit-mono": ("font-commit-mono", None),
    "cozette": ("font-cozette", None),
    "departure-mono": ("font-departure-mono", None),
    "dm-mono": ("font-dm-mono", None),
    "fragment-mono": ("font-fragment-mono", None),
    "geist": ("font-geist-mono", None),
    "google-sans-code": ("font-google-sans-code", None),
    "intel-one-mono": ("font-intel-one-mono", None),
    "ioskeley": ("font-ioskeley-mono", None),
    "jetbrainsmono": ("font-jetbrains-mono", None),
    "julia-mono": ("font-juliamono", None),
    "maple": ("font-maple-mono", None),
    "martian-mono": ("font-martian-mono", r"MartianMono-Std"),
    "miracode": ("font-miracode", None),
    "mona-sans-mono": ("font-mona-sans", r"Mono"),
    "monaspace-argon": ("font-monaspace", r"Argon"),
    "monaspace-krypton": ("font-monaspace", r"Krypton"),
    "monaspace-neon": ("font-monaspace", r"Neon"),
    "monaspace-radon": ("font-monaspace", r"Radon"),
    "monaspace-xenon": ("font-monaspace", r"Xenon"),
    "monocraft": ("font-monocraft", None),
    "myna": ("font-myna", None),
    "nordwand-mono": ("font-nordwand-mono", None),
    "oxproto": ("font-0xproto", None),
    "paper": ("font-paper-mono", None),
    "psudo": ("font-psudofont-liga-mono", None),
    "reddit-sans": ("font-reddit-mono", None),
    "sono": ("font-sono", None),
    "twilio-sans-mono": ("font-twilio-sans-mono", None),
}

FONT_FILE = re.compile(r"\.(ttf|ttc|otf|otc)$", re.I)
TRUETYPE_FILE = re.compile(r"\.(ttf|ttc)$", re.I)
JUNK_PATH = re.compile(r"(^|/)(__MACOSX|\._|\.git/)", re.I)
FACE_RULE = re.compile(
    r'font-family:\s*"([^"]+)";\s*font-weight:\s*([^;]+);\s*font-style:\s*([^;]+);'
    r'\s*src:\s*url\("\./([^"]+)"\)')


def read_url(url: str, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "noomz-themes font report"})
    for attempt in range(attempts - 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def webfont_faces(stylesheet: str) -> dict[str, list[dict[str, str]]]:
    faces: dict[str, list[dict[str, str]]] = {}
    for key, weight, style, path in FACE_RULE.findall(stylesheet):
        faces.setdefault(key, []).append(
            {"weight": weight.strip(), "style": style.strip(), "url": f"{SITE}/fonts/{path}"})
    return faces


def fetch_cask_archive(token: str, version_cache: dict[str, tuple[str, str]]) -> tuple[str, str]:
    if token not in version_cache:
        env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1"}
        subprocess.run(["brew", "fetch", "--cask", token], check=True, capture_output=True,
                       text=True, env=env)
        path = subprocess.run(["brew", "--cache", "--cask", token], check=True,
                              capture_output=True, text=True, env=env).stdout.strip()
        info = subprocess.run(["brew", "info", "--cask", "--json=v2", token], check=True,
                              capture_output=True, text=True, env=env).stdout
        version_cache[token] = (path, json.loads(info)["casks"][0]["version"])
    return version_cache[token]


def members(archive: str) -> dict[str, bytes]:
    """Font files inside a download, by archive path. Paths are only ever matched."""
    if FONT_FILE.search(archive):
        with open(archive, "rb") as handle:
            return {os.path.basename(archive): handle.read()}
    found: dict[str, bytes] = {}
    # Google Fonts casks arrive as a sparse git checkout, not a file.
    if os.path.isdir(archive):
        for root, _dirs, names in os.walk(archive):
            for name in names:
                path = os.path.join(root, name)
                relative = os.path.relpath(path, archive)
                if FONT_FILE.search(name) and not JUNK_PATH.search(relative):
                    with open(path, "rb") as handle:
                        found[relative] = handle.read()
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if FONT_FILE.search(info.filename) and not JUNK_PATH.search(info.filename):
                    found[info.filename] = bundle.read(info)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as bundle:
            for info in bundle.getmembers():
                if info.isfile() and FONT_FILE.search(info.name) and not JUNK_PATH.search(info.name):
                    found[info.name] = bundle.extractfile(info).read()
    return found


def write_cask_files(archive: str, pattern: str | None, target: str) -> list[str]:
    files = members(archive)
    if pattern:
        files = {path: data for path, data in files.items() if re.search(pattern, path, re.I)}
    # A release often ships one design as both TTF and OTF. Measuring both would
    # count every face twice, so TrueType wins when both are present.
    truetype = {path: data for path, data in files.items() if TRUETYPE_FILE.search(path)}
    files = truetype or files
    written = []
    for path, data in sorted(files.items()):
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", path)
        with open(os.path.join(target, name), "wb") as out:
            out.write(data)
        written.append(name)
    return written


def write_static_instances(target: str, files: list[str]) -> list[str]:
    """Give a variable-only family one static file per named instance.

    A variable file measures at its default instance, and several Google Fonts builds
    default to Thin or ExtraLight, which would score the wrong weight. Measuring each
    named instance also gives the family a real weight ladder. The variable file stays
    in the set, so the family keeps credit for being variable.
    """
    paths = [os.path.join(target, name) for name in files]
    fonts = [TTFont(path, lazy=True) if not path.lower().endswith((".ttc", ".otc")) else None
             for path in paths]
    is_variable_only = bool(fonts) and all(font is not None and "fvar" in font for font in fonts)
    for font in fonts:
        if font is not None:
            font.close()
    if not is_variable_only:
        return []
    written = []
    for path in paths:
        source = TTFont(path)
        for instance in source["fvar"].instances:
            label = source["name"].getDebugName(instance.subfamilyNameID)
            font = instancer.instantiateVariableFont(TTFont(path), dict(instance.coordinates))
            for name_id, value in ((2, label), (17, label)):
                font["name"].setName(value, name_id, 3, 1, 0x409)
            if "wght" in instance.coordinates:
                font["OS/2"].usWeightClass = int(instance.coordinates["wght"])
            stem = os.path.basename(path).rsplit(".", 1)[0]
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{stem}-instance-{label}.ttf")
            font.save(os.path.join(target, name))
            font.close()
            written.append(name)
        source.close()
    return written


def write_webfont_files(faces: list[dict[str, str]], target: str) -> list[str]:
    written = []
    with tempfile.TemporaryDirectory() as scratch:
        for face in faces:
            source = os.path.join(scratch, os.path.basename(face["url"]))
            with open(source, "wb") as out:
                out.write(read_url(face["url"]))
            font = TTFont(source)
            font.flavor = None
            extension = ".otf" if "CFF " in font or "CFF2" in font else ".ttf"
            name = os.path.basename(face["url"]).rsplit(".", 1)[0] + extension
            font.save(os.path.join(target, name))
            font.close()
            written.append(name)
    return written


def fetch_one(key: str, entry: dict[str, Any], faces: list[dict[str, str]], cache: str,
              prefer: str, version_cache: dict[str, tuple[str, str]]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": key, "name": entry["name"], "year": entry["year"], "license": entry.get("license"),
        "author": entry.get("author"), "website": entry.get("website"),
        "webfont_faces": faces, "source": "none", "files": [], "status": "fetched",
    }
    if entry.get("license") == "commercial":
        row["webfont_faces"] = []
        row["status"] = "skipped: commercial licence, no free file to measure"
        return row
    target = os.path.join(cache, key)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    cask = CASKS.get(key) if prefer == "cask" else None
    cask_error = None
    if cask:
        token, pattern = cask
        try:
            archive, version = fetch_cask_archive(token, version_cache)
            row["files"] = write_cask_files(archive, pattern, target)
            if row["files"]:
                row["static_instances"] = write_static_instances(target, row["files"])
                row.update(source="cask", cask=token, version=version)
                return row
            cask_error = f"{token} held no matching font file"
        except (subprocess.CalledProcessError, OSError, zipfile.BadZipFile) as error:
            cask_error = f"{token}: {error}"
    if not faces:
        row["status"] = f"failed: {cask_error or 'no webfont listed in the catalogue'}"
        return row
    try:
        row["files"] = write_webfont_files(faces, target)
        row["source"] = "webfont"
        if cask_error:
            row["note"] = f"cask unavailable, used webfont ({cask_error})"
    except Exception as error:
        row["status"] = f"failed: {error}"
    return row


def serve_webfont(face: dict[str, str]) -> str | None:
    """Put one webfont beside the report. `file` is set only if the font is on disk."""
    face.pop("file", None)
    match = WEBFONT_URL.fullmatch(face["url"])
    if not match:
        print(f"  not served, unexpected url: {face['url']}")
        return None
    relative = f"fonts/{match.group(1)}"
    path = os.path.join(REPORT_DIR, relative)
    if not os.path.exists(path):
        try:
            data = read_url(face["url"])
        except Exception as error:
            print(f"  not served, {relative}: {error}")
            return None
        if data[:4] != b"wOF2":
            print(f"  not served, not a woff2 file: {relative}")
            return None
        if len(data) > MAX_SERVED_BYTES:
            print(f"  not served, {len(data) / 2 ** 20:.2f} MiB is over the cap: {relative}")
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f"{path}.part", "wb") as out:
            out.write(data)
        os.replace(f"{path}.part", path)
    face["file"] = relative
    return relative


def serve_webfonts(rows: list[dict[str, Any]], workers: int) -> None:
    faces = [face for row in rows for face in row["webfont_faces"]]
    with ThreadPoolExecutor(workers) as pool:
        served = {relative for relative in pool.map(serve_webfont, faces) if relative}
    # Whatever no face claims would still be published: a crashed run's .part, a dropped font.
    size = 0
    for root, _dirs, names in os.walk(os.path.join(REPORT_DIR, "fonts")):
        for name in names:
            path = os.path.join(root, name)
            if os.path.relpath(path, REPORT_DIR) in served:
                size += os.path.getsize(path)
            else:
                os.remove(path)
    print(f"served {len(served)} of {len(faces)} webfonts, {size / 2 ** 20:.2f} MiB")


def fetch_manifest(args: argparse.Namespace) -> dict[str, Any]:
    commit = subprocess.run(["git", "ls-remote", REPO, "gh-pages"], check=True,
                            capture_output=True, text=True).stdout.split()[0]
    catalogue = json.loads(read_url(f"{RAW}/{commit}/fonts.json"))
    stylesheet = read_url(f"{RAW}/{commit}/fonts/stylesheet.css").decode()
    faces = webfont_faces(stylesheet)
    # A key names a cache directory that fetch_one deletes and recreates.
    unsafe = [key for key in catalogue if not CATALOGUE_KEY.fullmatch(key)]
    for key in unsafe:
        print(f"  skipped, unsafe catalogue key: {key!r}")
    selected = sorted(((key, entry) for key, entry in catalogue.items()
                       if key not in unsafe and entry["year"] > CUTOFF_YEAR),
                      key=lambda item: (item[1]["year"], item[0]))

    os.makedirs(args.cache, exist_ok=True)
    version_cache: dict[str, tuple[str, str]] = {}
    # One archive can serve several entries, so each cask downloads once, before any entry reads it.
    if args.prefer == "cask":
        tokens = sorted({CASKS[key][0] for key, entry in selected
                         if key in CASKS and entry.get("license") != "commercial"})

        def prefetch(token: str) -> None:
            try:
                fetch_cask_archive(token, version_cache)
            except subprocess.CalledProcessError as error:
                print(f"  cask {token} failed: {error.stderr.strip()[:200]}")

        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(prefetch, tokens))

    with ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(
            lambda item: fetch_one(item[0], item[1], faces.get(item[0], []), args.cache,
                                   args.prefer, version_cache),
            selected))

    for row in rows:
        print(f"{row['year']} {row['key']:<28} {row['source']:<8} {len(row['files']):>4} "
              f"{row['status'] if row['status'] != 'fetched' else ''}")
    return {
        "catalogue": {"url": SITE, "repo_commit": commit, "entries": len(catalogue),
                      "fetched": date.today().isoformat()},
        "cutoff_year": CUTOFF_YEAR,
        "cache": args.cache,
        "fonts": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=".cache/recent-fonts")
    parser.add_argument("--manifest", default="docs/recent-fonts.json")
    parser.add_argument("--prefer", choices=["cask", "webfont"], default="cask",
                        help="webfont measures only the catalogue's files, to size their bias")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--webfonts-only", action="store_true",
                        help="refresh docs/fonts from the existing manifest, measuring nothing")
    args = parser.parse_args()

    if args.webfonts_only:
        with open(args.manifest) as handle:
            manifest = json.load(handle)
    else:
        manifest = fetch_manifest(args)
    # A --prefer webfont run only sizes a bias. The report never reads its manifest.
    if args.prefer == "cask":
        serve_webfonts(manifest["fonts"], args.workers)
    os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
    with open(args.manifest, "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(f"wrote {args.manifest}: {len(manifest['fonts'])} entries")


if __name__ == "__main__":
    main()
