#!/usr/bin/env python3
"""Independent LML install.xml -> portable RDR2 asset-overlay staging package.

Reads public/user-supplied mod declarations; DOES NOT load, decompile or copy
Lenny's proprietary loader. Creates an offline data package, not a PS4 PRX.
Python >= 3.9; standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

FORMAT = "rdr2-lml-overlay/1"
MAP_MAGIC = "LML_OVERLAY_V1"
MAX_XML = 2_000_000
MAX_RESOURCE = 256 * 1024 * 1024
SUPPORTED = {"FileReplacement", "StreamingFile", "DataFile"}
SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]+):/(.+)$")
TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
BAD = re.compile(r"[\x00-\x1f\x7f]")


class ConversionError(ValueError):
    pass


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def relative_path(raw: str) -> str:
    if not raw or BAD.search(raw):
        raise ConversionError(f"Invalid or missing relative path: {raw!r}")
    raw = raw.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ConversionError(f"Absolute path not allowed: {raw!r}")
    pieces = raw.split("/")
    if not pieces or any(part in ("", ".", "..") for part in pieces):
        raise ConversionError(f"Path traversal or empty component: {raw!r}")
    if any(":" in part for part in pieces):
        raise ConversionError(f"Unexpected ':' in relative path: {raw!r}")
    return "/".join(pieces)


def game_path(raw: str) -> str:
    if BAD.search(raw or ""):
        raise ConversionError(f"Invalid game path: {raw!r}")
    normalized = (raw or "").replace("\\", "/")
    found = SCHEME.fullmatch(normalized)
    if not found:
        raise ConversionError(f"Game path must have an archive namespace, e.g. update:/...: {raw!r}")
    return found.group(1).lower() + ":/" + relative_path(found.group(2)).lower()


def stream_name(raw: str) -> str:
    return relative_path(raw).lower()


def data_name(kind: str, raw: str) -> str:
    if not TYPE.fullmatch(kind):
        raise ConversionError(f"Invalid data-file type: {kind!r}")
    return kind.upper() + "/" + relative_path(raw).rsplit("/", 1)[-1].lower()


def resolve_resource(mod_dir: Path, path_text: str) -> tuple[Path, str]:
    rel = relative_path(path_text)
    source = mod_dir.joinpath(*rel.split("/"))
    # Case-insensitive matching is deliberately not simulated: incompatible
    # casing in source mod files must be corrected, not silently guessed.
    if source.is_symlink() or not source.is_file():
        raise ConversionError(f"Missing, renamed or linked resource: {source}")
    if not source.resolve().is_relative_to(mod_dir.resolve()):
        raise ConversionError(f"Resource escapes mod directory: {source}")
    if source.stat().st_size > MAX_RESOURCE:
        raise ConversionError(f"Resource exceeds {MAX_RESOURCE} bytes: {source}")
    return source, rel


def file_digest(path: Path) -> str:
    dig = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            dig.update(block)
    return dig.hexdigest()



def inspect_asset(path: Path) -> tuple[str, str]:
    """Best-effort file classification. It never converts game resource bytes."""
    with path.open("rb") as stream:
        prefix = stream.read(512)
    prefix = prefix.lstrip(b"\xef\xbb\xbf\x00 \t\r\n")
    suffix = path.suffix.lower()
    is_xml = prefix.startswith(b"<")
    if is_xml and suffix in {".ymt", ".ymap", ".ytyp", ".ymf"}:
        return "rage_xml", "requires_rage_xml_serialization"
    if is_xml and suffix == ".meta":
        return "xml_metadata", "requires_game_data_parser_validation"
    if suffix == ".gxt2" and prefix.startswith(b"#"):
        return "lml_text_string_table", "requires_string_table_translation"
    if prefix.startswith(b"RSC8"):
        return "rsc8_binary", "requires_ps4_resource_compatibility_validation"
    return "unknown", "requires_manual_resource_format_verification"

def parse_xml(manifest: Path) -> ET.Element:
    raw = manifest.read_bytes()
    if len(raw) > MAX_XML or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ConversionError(f"Unsafe XML declaration or oversized manifest: {manifest}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ConversionError(f"Invalid install.xml at {manifest}: {exc}") from exc
    if root.tag != "EasyInstall":
        raise ConversionError(f"Expected EasyInstall root: {manifest}")
    return root


def slug(mod_relative: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", mod_relative.casefold()).strip("-")
    return (value[:70] or "mod") + "-" + hashlib.sha256(mod_relative.encode()).hexdigest()[:8]


def parse_package(xml_path: Path, source_root: Path,
                  selected_groups: set[str], all_groups: bool) -> tuple[dict, list[dict], list[str]]:
    mod_dir = xml_path.parent
    mod_rel = mod_dir.relative_to(source_root).as_posix()
    root = parse_xml(xml_path)
    mod_id = slug(mod_rel)
    mod = {
        "id": mod_id,
        "source_folder": mod_rel,
        "title": _text(root.find("Name")) or mod_dir.name,
        "author": _text(root.find("Author")),
        "version": _text(root.find("Version")),
        "groups": [],
        "selected_groups": [],
    }
    warnings: list[str] = []
    refs: dict[str, list[str]] = {}
    for group in root.findall("./ResourceGroups/ResourceGroup"):
        group_name = group.get("name", "").strip()
        if not group_name:
            raise ConversionError(f"ResourceGroup has no name: {xml_path}")
        tokens = [_text(r) for r in group.findall("./Resources/Resource")]
        if not tokens or not all(tokens):
            raise ConversionError(f"ResourceGroup has empty resource references: {group_name}")
        mod["groups"].append(group_name)
        for token in tokens:
            refs.setdefault(token, []).append(group_name)
    chosen = set(mod["groups"]) if all_groups else set(mod["groups"]) & selected_groups
    mod["selected_groups"] = sorted(chosen)
    resources_root = root.find("Resources")
    if resources_root is None:
        raise ConversionError(f"Missing Resources block: {xml_path}")
    entries = []
    available_resource_ids = set()
    for idx, res in enumerate(resources_root):
        if res.tag != "Resource":
            raise ConversionError(f"Unsupported top-level Resource tag {res.tag!r} in {xml_path}")
        key = res.get("scriptName") or res.get("name") or f"resource_{idx}"
        if key in available_resource_ids:
            raise ConversionError(f"Duplicate resource identifier: {key}")
        available_resource_ids.add(key)
        gated_by = refs.get(key, [])
        if gated_by and not (set(gated_by) & chosen):
            warnings.append(f"{mod['title']}: disabled grouped resource {key!r}")
            continue
        for spec in res:
            if spec.tag not in SUPPORTED:
                raise ConversionError(
                    f"Unsupported LML resource tag {spec.tag!r} in {xml_path}; "
                    "not silently discarded"
                )
            kind = {"FileReplacement": "R", "StreamingFile": "S", "DataFile": "D"}[spec.tag]
            if kind == "R":
                file_path = _text(spec.find("FilePath"))
                key_path = game_path(_text(spec.find("GamePath")))
            else:
                file_path = _text(spec.find("FilePath")) or _text(spec)
                if kind == "S":
                    game_names = [_text(n) for n in spec.findall("GamePath")]
                    if spec.find("DlcName") is not None:
                        raise ConversionError("DlcName streaming assets require a game-specific resolver")
                    key_path = stream_name(game_names[0] if game_names else Path(file_path).name)
                    if len(game_names) > 1:
                        raise ConversionError("Multi-GamePath streaming aliases unsupported in v1")
                else:
                    file_type = spec.get("type", "AUTO").strip() or "AUTO"
                    key_path = data_name(file_type, Path(file_path).name)
                    if file_type == "AUTO":
                        warnings.append(f"{mod['title']}: inferred DataFile type not implemented; AUTO requires runtime handling")
            path, src_rel = resolve_resource(mod_dir, file_path)
            format_hint, processing = inspect_asset(path)
            payload = f"payload/{mod_id}/{src_rel}"
            entries.append({
                "kind": kind, "key": key_path, "source": mod_rel + "/" + src_rel,
                "payload": payload, "bytes": path.stat().st_size,
                "sha256": file_digest(path),
                "mod_id": mod_id, "resource": key,
                "selected_by": sorted(set(gated_by) & chosen),
                "format_hint": format_hint,
                "integration_requirement": processing,
            })

    unknown_groups = set(refs) - available_resource_ids
    if unknown_groups:
        raise ConversionError(f"ResourceGroup refers to unknown scriptName(s) in {xml_path}: {sorted(unknown_groups)}")
    if mod["groups"] and not chosen:
        warnings.append(f"{mod['title']}: no ResourceGroup selected (explicit opt-in required)")
    return mod, entries, warnings


def compile_catalog(src_root: Path, selected_groups: set[str], all_groups: bool) -> dict:
    if not src_root.is_dir():
        raise ConversionError(f"Source mod directory not found: {src_root}")
    manifests = sorted(src_root.rglob("install.xml"))
    if not manifests:
        raise ConversionError(f"No install.xml under {src_root}")
    mods, entries, warnings = [], [], []
    seen = {}
    for xml_path in manifests:
        mod, subset, notes = parse_package(xml_path, src_root, selected_groups, all_groups)
        mods.append(mod)
        warnings.extend(notes)
        for entry in subset:
            collision_key = (entry["kind"], entry["key"].casefold())
            if collision_key in seen:
                raise ConversionError(f"Ambiguous overlay key {collision_key}: {seen[collision_key]} and {entry['source']}")
            seen[collision_key] = entry["source"]
            entries.append(entry)
    known = {name for m in mods for name in m["groups"]}
    unknown = selected_groups - known
    if unknown:
        raise ConversionError(f"Unknown requested ResourceGroup names: {sorted(unknown)}")
    counts = Counter(e["kind"] for e in entries)
    formats = Counter(e["format_hint"] for e in entries)
    if formats["rage_xml"]:
        warnings.append(
            f"{formats['rage_xml']} RAGE-format files contain XML text; a game-specific "
            "serializer/PSO compatibility layer is required before console loading"
        )
    if formats["lml_text_string_table"]:
        warnings.append("LML .gxt2 text tables require a game-specific string registration layer")
    return {
        "format": FORMAT,
        "purpose": "offline-overlay-data; game hook/PRX not included",
        "source_root": str(src_root.resolve()),
        "selection": {"all_groups": all_groups, "groups": sorted(selected_groups)},
        "mods": mods,
        "summary": {
            "mods": len(mods), "entries": len(entries),
            "file_replacements": counts["R"],
            "streaming_files": counts["S"],
            "data_files": counts["D"],
            "payload_bytes": sum(e["bytes"] for e in entries),
            "xml_rage_resources": formats["rage_xml"],
            "xml_metadata_files": formats["xml_metadata"],
            "text_string_tables": formats["lml_text_string_table"],
            "native_rsc8_files": formats["rsc8_binary"],
        },
        "entries": entries,
        "warnings": warnings,
        "runtime_requirements": [
            "R: redirect game/archive namespace file opens to replacement payload",
            "S: register streaming asset by its game resource name",
            "D: register and parse data file by its game data type",
            "RDR2 PS4 module loader/engine integration is not provided",
            "Asset binaries copied byte-for-byte; PS4 game-version/format compatibility is unknown",
        ],
    }


def emit_stage(catalog: dict, source_root: Path, output: Path) -> None:
    if output.exists():
        raise ConversionError(f"Output already exists (nothing overwritten): {output}")
    if output.resolve() == source_root.resolve():
        raise ConversionError("Output cannot replace source directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="lml-stage-", dir=output.parent))
    try:
        for entry in catalog["entries"]:
            src = source_root / Path(entry["source"])
            relative = relative_path(entry["payload"])
            dst = staging / Path(relative)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copyfile(src, dst)
            if dst.stat().st_size != entry["bytes"] or file_digest(dst) != entry["sha256"]:
                raise ConversionError(f"Payload hash mismatch: {dst}")
        mapping = [MAP_MAGIC, "# kind<TAB>resource-key<TAB>payload-relative<TAB>sha256<TAB>bytes"]
        for entry in catalog["entries"]:
            for cell in (entry["kind"], entry["key"], entry["payload"], entry["sha256"]):
                if BAD.search(cell):
                    raise ConversionError("Map cell contains a control character")
            mapping.append("\t".join([entry["kind"], entry["key"], entry["payload"],
                                      entry["sha256"], str(entry["bytes"])]))
        (staging / "overlay.map").write_text("\n".join(mapping) + "\n", encoding="utf-8")
        (staging / "catalog.json").write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8"
        )
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Root containing mods with install.xml")
    parser.add_argument("--out", type=Path, help="New output directory; never overwritten")
    parser.add_argument("--group", action="append", default=[], help="Enable this ResourceGroup (repeat)")
    parser.add_argument("--all-groups", action="store_true", help="Enable all ResourceGroups, explicitly")
    parser.add_argument("--dry-run", action="store_true", help="Validate and show summary without creating files")
    args = parser.parse_args()
    try:
        source = args.source.resolve()
        catalog = compile_catalog(source, set(args.group), args.all_groups)
        print(json.dumps({
            "summary": catalog["summary"],
            "mods": [{"name": m["title"], "groups": m["groups"],
                      "selected": m["selected_groups"]} for m in catalog["mods"]],
            "warnings": catalog["warnings"],
        }, indent=2, ensure_ascii=False))
        if not args.dry_run:
            if args.out is None:
                parser.error("--out required unless --dry-run")
            emit_stage(catalog, source, args.out.resolve())
            print(f"Created stage: {args.out.resolve()}")
        return 0
    except (OSError, ConversionError) as exc:
        print(f"LML conversion failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
