import json
import re
import sqlite3
import urllib.request
from pathlib import Path

import brotli
import requests

REGIONS = ["jp", "cn", "tw"]
RAW_OUTPUT_DIR = Path("build/raw")


def load_local_version(region):
    filename = Path(f"{region.upper()}_pcr_data.py")
    if not filename.exists():
        return None

    version = None
    db_hash = None
    with filename.open("r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^TRUTH_VERSION\s*=\s*"(.+)"', line)
            if m:
                version = m.group(1)
            m = re.match(r'^DB_HASH\s*=\s*"(.+)"', line)
            if m:
                db_hash = m.group(1)

    if version and db_hash:
        return {"truthVersion": version, "hash": db_hash}
    return None


def check_db_version(region):
    url = "https://wthee.xyz/pcr/api/v1/db/info/v2"
    payload = {"regionCode": region}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  Failed to fetch {region.upper()} version info: {e}")
        return None


def get_db_path(region):
    return Path(region) / f"redive_{region}.db"


def check_update(region):
    remote_info = check_db_version(region)
    if not remote_info or remote_info.get("status") != 0:
        return False, None, None

    remote_version = remote_info["data"]["truthVersion"]
    remote_hash = remote_info["data"]["hash"]

    local_info = load_local_version(region)
    if local_info is None:
        return True, remote_version, remote_hash

    if local_info.get("truthVersion") != remote_version or local_info.get("hash") != remote_hash:
        return True, remote_version, remote_hash

    return False, remote_version, remote_hash


def download_database(region):
    db_url = f"https://wthee.xyz/db/redive_{region}.db.br"
    db_path = get_db_path(region)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_suffix(db_path.suffix + ".br")

    try:
        print(f"  Downloading: {db_url}")
        urllib.request.urlretrieve(db_url, temp_path)
        print("  Download complete, decompressing...")

        decompressed_data = brotli.decompress(temp_path.read_bytes())
        db_path.write_bytes(decompressed_data)
        temp_path.unlink(missing_ok=True)
        print(f"  Decompressed to: {db_path}")
        return str(db_path)

    except Exception as e:
        print(f"  Download failed: {e}")
        temp_path.unlink(missing_ok=True)
        return None


def get_where_clause(region):
    if region in ["jp", "tw"]:
        return "(unit_id BETWEEN 100001 AND 169901) OR (unit_id BETWEEN 180001 AND 189901)"
    if region == "cn":
        return "(unit_id BETWEEN 100001 AND 170201) OR (unit_id BETWEEN 180001 AND 189901)"
    return "unit_id BETWEEN 100001 AND 189901"


def ensure_database_available(region, has_update):
    db_path = get_db_path(region)
    if has_update or not db_path.exists():
        if not has_update:
            print(f"  {region.upper()}: local database is missing; downloading for JJC raw JSON")
        return download_database(region)
    return str(db_path)


def extract_unit_data(db_path, region):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    where_clause = get_where_clause(region)

    cursor.execute(
        f"""
        SELECT unit_id, unit_name, search_area_width
        FROM unit_data
        WHERE {where_clause}
        ORDER BY unit_id
        """
    )
    unit_data = {
        row[0]: {"unit_name": row[1], "search_area_width": row[2]}
        for row in cursor.fetchall()
    }

    cursor.execute(
        f"""
        SELECT unit_id, unit_role_id
        FROM unit_role_data
        WHERE {where_clause}
        ORDER BY unit_id
        """
    )
    role_data = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute(
        f"""
        SELECT unit_id, talent_id
        FROM unit_talent
        WHERE {where_clause}
        ORDER BY unit_id
        """
    )
    talent_data = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    unavailable = {}
    unit_name = {}
    search_area_width = {}
    unit_role_id = {}
    talent_id = {}
    raw_units = {}

    for unit_id in sorted(unit_data.keys()):
        role = role_data.get(unit_id)
        talent = talent_data.get(unit_id)
        name = unit_data[unit_id]["unit_name"]
        area_width = unit_data[unit_id]["search_area_width"]

        raw_units[unit_id] = {
            "unit_id": unit_id,
            "unit_name": name,
            "search_area_width": area_width,
            "unit_role_id": role,
            "talent_id": talent,
        }

        if role is None or talent is None:
            unavailable[unit_id] = name
        else:
            unit_name[unit_id] = name
            search_area_width[unit_id] = area_width
            unit_role_id[unit_id] = role
            talent_id[unit_id] = talent

    return {
        "unavailable": unavailable,
        "unit_name": unit_name,
        "search_area_width": search_area_width,
        "unit_role_id": unit_role_id,
        "talent_id": talent_id,
        "raw_units": raw_units,
    }


def save_to_py(data, region, version, db_hash):
    filename = Path(f"{region.upper()}_pcr_data.py")
    with filename.open("w", encoding="utf-8", newline="\n") as f:
        f.write('"""Princess Connect Re:Dive game data. Generated by download_db.py."""\n\n')
        f.write(f'TRUTH_VERSION = "{version}"\n')
        f.write(f'DB_HASH = "{db_hash}"\n\n')

        f.write("UnavailableChara = {\n")
        for unit_id in sorted(data["unavailable"].keys()):
            name = data["unavailable"][unit_id]
            f.write(f"    {unit_id},   # {name}\n")
        f.write("}\n\n")

        f.write("UNIT_NAME = {\n")
        for unit_id in sorted(data["unit_name"].keys()):
            f.write(f"    {unit_id}: {data['unit_name'][unit_id]!r},\n")
        f.write("}\n\n")

        f.write("SEARCH_AREA_WIDTH = {\n")
        for unit_id in sorted(data["search_area_width"].keys()):
            f.write(f"    {unit_id}: {data['search_area_width'][unit_id]},\n")
        f.write("}\n\n")

        f.write("UNIT_ROLE_ID = {\n")
        for unit_id in sorted(data["unit_role_id"].keys()):
            f.write(f"    {unit_id}: {data['unit_role_id'][unit_id]},\n")
        f.write("}\n\n")

        f.write("TALENT_ID = {\n")
        for unit_id in sorted(data["talent_id"].keys()):
            f.write(f"    {unit_id}: {data['talent_id'][unit_id]},\n")
        f.write("}\n")

    print(f"  Saved data to {filename}")
    print(f"  - complete units: {len(data['unit_name'])}")
    print(f"  - partial units: {len(data['unavailable'])}")
    return filename


def save_raw_json(data, region, version, db_hash, output_dir=RAW_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{region}_units.json"
    payload = {
        "region": region,
        "truth_version": version,
        "db_hash": db_hash,
        "units": [data["raw_units"][unit_id] for unit_id in sorted(data["raw_units"].keys())],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Saved raw JSON to {output_path}")
    return output_path


def main():
    print("=" * 60)
    print("PCR database version check, download, and extraction tool")
    print("=" * 60)

    print("\n[Step 1] Checking versions...")
    update_info = {}

    for region in REGIONS:
        has_update, remote_version, remote_hash = check_update(region)
        update_info[region] = {
            "has_update": has_update,
            "version": remote_version,
            "hash": remote_hash,
        }
        if has_update:
            print(f"  {region.upper()}: update available -> {remote_version}")
        elif remote_version:
            print(f"  {region.upper()}: already latest -> {remote_version}")
        else:
            print(f"  {region.upper()}: version check failed")

    print("\n[Step 2] Downloading/updating databases and extracting data...")

    for region in REGIONS:
        info = update_info[region]
        if not info["version"]:
            print(f"  {region.upper()}: skipped because version check failed")
            continue

        if info["has_update"]:
            print(f"\n  >>> {region.upper()} needs update")

        db_path = ensure_database_available(region, info["has_update"])
        if not db_path:
            continue

        data = extract_unit_data(db_path, region)
        if info["has_update"]:
            save_to_py(data, region, info["version"], info["hash"])
        else:
            print(f"  {region.upper()}: already latest; skipped Python data file write")
        save_raw_json(data, region, info["version"], info["hash"])

    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
