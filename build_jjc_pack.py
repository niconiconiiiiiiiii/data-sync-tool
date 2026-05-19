import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import msgpack

SCHEMA_VERSION = 2
DEFAULT_OUTPUT_DIR = Path("dist")
DEFAULT_RAW_DIR = Path("build/raw")

PACK_ALLOWED_RANGES = ((1001, 1702), (1800, 1899))


def normalize_alias(value):
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def load_python_module(path):
    path = Path(path)
    module_name = f"_jjc_pack_source_{hashlib.sha1(str(path.resolve()).encode('utf-8')).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load Python data source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_raw_units(path):
    path = Path(path)
    if not path.exists():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    units = {int(item["unit_id"]): item for item in payload.get("units", [])}
    return units, payload


def normalize_unit_id(value):
    value = int(value)
    if value >= 100000:
        return value // 100
    return value


def normalize_unit_id_set(values):
    return {normalize_unit_id(value) for value in values}


def is_pack_unit_id(unit_id):
    unit_id = int(unit_id)
    return any(start <= unit_id <= end for start, end in PACK_ALLOWED_RANGES)


def load_region_data(py_path, raw_path=None):
    module = load_python_module(py_path)
    raw_units, raw_payload = load_raw_units(raw_path) if raw_path else ({}, None)
    unit_name = {int(k): v for k, v in getattr(module, "UNIT_NAME", {}).items()}
    search_area_width = {int(k): v for k, v in getattr(module, "SEARCH_AREA_WIDTH", {}).items()}
    unit_role_id = {int(k): v for k, v in getattr(module, "UNIT_ROLE_ID", {}).items()}
    talent_id = {int(k): v for k, v in getattr(module, "TALENT_ID", {}).items()}
    unavailable = normalize_unit_id_set(getattr(module, "UnavailableChara", set()))

    for unit_id, raw in raw_units.items():
        if raw.get("unit_name") is not None:
            unit_name.setdefault(unit_id, raw.get("unit_name"))
        if raw.get("search_area_width") is not None:
            search_area_width.setdefault(unit_id, raw.get("search_area_width"))
        if raw.get("unit_role_id") is not None:
            unit_role_id.setdefault(unit_id, raw.get("unit_role_id"))
        if raw.get("talent_id") is not None:
            talent_id.setdefault(unit_id, raw.get("talent_id"))

    return {
        "truth_version": str(getattr(module, "TRUTH_VERSION", raw_payload.get("truth_version") if raw_payload else "unknown")),
        "db_hash": str(getattr(module, "DB_HASH", raw_payload.get("db_hash") if raw_payload else "unknown")),
        "unit_name": unit_name,
        "search_area_width": search_area_width,
        "unit_role_id": unit_role_id,
        "talent_id": talent_id,
        "unavailable": unavailable,
        "raw_units": raw_units,
    }


def load_nickname_data(path):
    module = load_python_module(path)
    chara_nickname = {int(k): v for k, v in getattr(module, "CHARA_NICKNAME", {}).items()}
    chara_name = {int(k): list(v) for k, v in getattr(module, "CHARA_NAME", {}).items()}
    unavailable = normalize_unit_id_set(getattr(module, "UnavailableChara", set()))
    return {
        "display_nickname": chara_nickname,
        "aliases": chara_name,
        "unavailable": unavailable,
    }


def first_present(unit_id, sources, key):
    for source_name, data in sources:
        value = data[key].get(unit_id)
        if value is not None:
            return value, source_name
    return None, "unknown"


def first_present_nonzero(unit_id, sources, key):
    for source_name, data in sources:
        value = data[key].get(unit_id)
        if value not in (None, 0):
            return value, source_name
    return None, "unknown"


def unique_strings(values):
    seen = set()
    output = []
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if not value:
            continue
        key = normalize_alias(value)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def build_units(cn_data, jp_data, nickname_data):
    unit_ids = set()
    for data in [cn_data, jp_data]:
        for key in ["unit_name", "search_area_width", "unit_role_id", "talent_id", "raw_units"]:
            unit_ids.update(data[key].keys())
    unit_ids.update(nickname_data["display_nickname"].keys())
    unit_ids.update(nickname_data["aliases"].keys())

    unavailable = cn_data["unavailable"] | jp_data["unavailable"] | nickname_data["unavailable"]
    unit_ids = {unit_id for unit_id in unit_ids if is_pack_unit_id(unit_id) and unit_id not in unavailable}

    units = {}
    for unit_id in sorted(unit_ids):
        display_nickname = nickname_data["display_nickname"].get(unit_id)
        if display_nickname is None:
            alias_list = nickname_data["aliases"].get(unit_id, [])
            display_nickname = alias_list[0] if alias_list else str(unit_id)

        search_area_width, _ = first_present_nonzero(unit_id, [("cn", cn_data), ("jp", jp_data)], "search_area_width")
        role_id, _ = first_present(unit_id, [("cn", cn_data), ("jp", jp_data)], "unit_role_id")
        talent_id, _ = first_present(unit_id, [("cn", cn_data), ("jp", jp_data)], "talent_id")

        units[str(unit_id)] = {
            "unit_id": unit_id,
            "display_nickname": display_nickname,
            "search_area_width": search_area_width,
            "unit_role_id": role_id,
            "talent_id": talent_id,
        }
    return units


def build_alias_index(units, nickname_data):
    alias_index = {}
    conflicts = []
    for unit_key in sorted(units.keys(), key=lambda value: int(value)):
        unit_id = int(unit_key)
        aliases = unique_strings(
            [units[unit_key]["display_nickname"]]
            + nickname_data["aliases"].get(unit_id, [])
        )
        for alias in aliases:
            normalized = normalize_alias(alias)
            if not normalized:
                continue
            owner = alias_index.get(normalized)
            if owner is None:
                alias_index[normalized] = unit_id
            elif owner != unit_id:
                conflicts.append(
                    {
                        "alias": normalized,
                        "kept_unit_id": owner,
                        "dropped_unit_id": unit_id,
                        "dropped_value": alias,
                    }
                )
    return alias_index, conflicts


def json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def add_optional_assets(zf, assets_dir):
    assets_dir = Path(assets_dir) if assets_dir else None
    if not assets_dir or not assets_dir.exists():
        zf.writestr("assets/README.txt", "No optional assets were bundled for this pack.\n")
        return []

    bundled = []
    for path in sorted(assets_dir.rglob("*")):
        if path.is_file():
            arcname = "assets/" + path.relative_to(assets_dir).as_posix()
            zf.write(path, arcname)
            bundled.append(arcname)
    return bundled


def build_pack(
    cn_path="CN_pcr_data.py",
    jp_path="JP_pcr_data.py",
    nickname_path="_pcr_data.py",
    output_dir=DEFAULT_OUTPUT_DIR,
    generated_at=None,
    cn_raw_path=None,
    jp_raw_path=None,
    assets_dir=None,
    nickname_revision=None,
):
    cn_path = Path(cn_path)
    jp_path = Path(jp_path)
    nickname_path = Path(nickname_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cn_data = load_region_data(cn_path, cn_raw_path if cn_raw_path and Path(cn_raw_path).exists() else None)
    jp_data = load_region_data(jp_path, jp_raw_path if jp_raw_path and Path(jp_raw_path).exists() else None)
    nickname_data = load_nickname_data(nickname_path)
    nickname_revision = nickname_revision or os.environ.get("NICKNAME_SOURCE_REVISION") or "local"
    generated_at = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    units = build_units(cn_data, jp_data, nickname_data)
    alias_index, conflicts = build_alias_index(units, nickname_data)
    pack_version = f"cn-{cn_data['truth_version']}-nick-{nickname_revision}"

    units_payload = {"schema_version": SCHEMA_VERSION, "units": units}
    aliases_payload = {"schema_version": SCHEMA_VERSION, "aliases": alias_index, "conflicts": conflicts}
    vision_payload = {"schema_version": SCHEMA_VERSION, "templates": {}}

    units_blob = json_bytes(units_payload)
    aliases_blob = json_bytes(aliases_payload)
    vision_blob = msgpack.packb(vision_payload, use_bin_type=True)
    checksums_payload = {
        "schema_version": SCHEMA_VERSION,
        "files": {
            "units.json": sha256_bytes(units_blob),
            "aliases.json": sha256_bytes(aliases_blob),
            "vision_templates.msgpack": sha256_bytes(vision_blob),
        },
    }
    checksums_blob = json_bytes(checksums_payload)
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "pack_version": pack_version,
        "generated_at": generated_at,
        "sources": {
            "cn": {"truth_version": cn_data["truth_version"], "db_hash": cn_data["db_hash"], "path": str(cn_path)},
            "jp": {"truth_version": jp_data["truth_version"], "db_hash": jp_data["db_hash"], "path": str(jp_path)},
            "nickname": {"revision": nickname_revision, "path": str(nickname_path)},
        },
        "counts": {
            "units": len(units),
            "aliases": len(alias_index),
            "alias_conflicts": len(conflicts),
        },
        "checksums": checksums_payload["files"],
    }
    manifest_blob = json_bytes(manifest_payload)

    pack_path = output_dir / f"jjc-pack-{pack_version}.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_blob)
        zf.writestr("units.json", units_blob)
        zf.writestr("aliases.json", aliases_blob)
        zf.writestr("vision_templates.msgpack", vision_blob)
        zf.writestr("checksums.json", checksums_blob)
        add_optional_assets(zf, assets_dir)

    latest_path = output_dir / "jjc-pack-latest.zip"
    if latest_path != pack_path:
        shutil.copyfile(pack_path, latest_path)
    return pack_path


def main():
    parser = argparse.ArgumentParser(description="Build JJC data pack from PCR data sources.")
    parser.add_argument("--cn", default="CN_pcr_data.py", help="CN generated Python data path")
    parser.add_argument("--jp", default="JP_pcr_data.py", help="JP generated Python data path")
    parser.add_argument("--nickname", default="_pcr_data.py", help="Nickname Python data path")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Pack output directory")
    parser.add_argument("--assets-dir", default=None, help="Optional asset directory to bundle under assets/")
    parser.add_argument("--nickname-revision", default=None, help="Nickname source revision recorded in manifest")
    args = parser.parse_args()

    pack_path = build_pack(
        cn_path=args.cn,
        jp_path=args.jp,
        nickname_path=args.nickname,
        output_dir=args.output_dir,
        assets_dir=args.assets_dir,
        nickname_revision=args.nickname_revision,
        cn_raw_path=DEFAULT_RAW_DIR / "cn_units.json",
        jp_raw_path=DEFAULT_RAW_DIR / "jp_units.json",
    )
    print(f"JJC pack generated: {pack_path}")


if __name__ == "__main__":
    main()
