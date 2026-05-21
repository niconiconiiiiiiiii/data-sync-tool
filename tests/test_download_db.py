import json
import sqlite3

from download_db import extract_unit_data, get_where_clause, save_raw_json


def test_get_where_clause_uses_jjc_v3_6_digit_unit_ranges():
    assert get_where_clause("cn") == "(unit_id BETWEEN 100001 AND 170201) OR (unit_id BETWEEN 180001 AND 189901)"
    assert get_where_clause("jp") == "(unit_id BETWEEN 100001 AND 169901) OR (unit_id BETWEEN 180001 AND 189901)"
    assert get_where_clause("tw") == "(unit_id BETWEEN 100001 AND 169901) OR (unit_id BETWEEN 180001 AND 189901)"


def test_extract_unit_data_keeps_6_digit_unit_ids_in_raw_units(tmp_path):
    db_path = tmp_path / "redive_cn.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        '''
        CREATE TABLE unit_data (
            unit_id INTEGER PRIMARY KEY,
            unit_name TEXT NOT NULL,
            search_area_width INTEGER
        );
        CREATE TABLE unit_role_data (
            unit_id INTEGER PRIMARY KEY,
            unit_role_id INTEGER
        );
        CREATE TABLE unit_talent (
            unit_id INTEGER PRIMARY KEY,
            talent_id INTEGER
        );
        INSERT INTO unit_data VALUES (100101, '\u65e5\u548c\u8389', 200);
        INSERT INTO unit_data VALUES (100201, '\u4f18\u8863', 800);
        INSERT INTO unit_role_data VALUES (100101, 1);
        INSERT INTO unit_talent VALUES (100101, 1);
        '''
    )
    conn.commit()
    conn.close()

    data = extract_unit_data(str(db_path), "cn")

    assert data["unit_name"] == {100101: "\u65e5\u548c\u8389"}
    assert data["unavailable"] == {100201: "\u4f18\u8863"}
    assert data["raw_units"][100101] == {
        "unit_id": 100101,
        "unit_name": "\u65e5\u548c\u8389",
        "search_area_width": 200,
        "unit_role_id": 1,
        "talent_id": 1,
    }
    assert data["raw_units"][100201] == {
        "unit_id": 100201,
        "unit_name": "\u4f18\u8863",
        "search_area_width": 800,
        "unit_role_id": None,
        "talent_id": None,
    }


def test_save_raw_json_writes_region_metadata_and_all_raw_units(tmp_path):
    data = {
        "raw_units": {
            100201: {
                "unit_id": 100201,
                "unit_name": "\u4f18\u8863",
                "search_area_width": 800,
                "unit_role_id": None,
                "talent_id": None,
            }
        }
    }

    output_path = save_raw_json(data, "cn", "202605151116", "hash-1", output_dir=tmp_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["region"] == "cn"
    assert payload["truth_version"] == "202605151116"
    assert payload["db_hash"] == "hash-1"
    assert payload["units"] == [
        {
            "unit_id": 100201,
            "unit_name": "\u4f18\u8863",
            "search_area_width": 800,
            "unit_role_id": None,
            "talent_id": None,
        }
    ]


def test_ensure_database_available_downloads_when_no_update_but_db_missing(monkeypatch, tmp_path):
    import download_db

    db_path = tmp_path / "cn" / "redive_cn.db"
    calls = []

    monkeypatch.setattr(download_db, "get_db_path", lambda region: db_path)
    monkeypatch.setattr(download_db, "download_database", lambda region: calls.append(region) or str(db_path))

    assert download_db.ensure_database_available("cn", has_update=False) == str(db_path)
    assert calls == ["cn"]


def test_ensure_database_available_reuses_existing_db_when_no_update(monkeypatch, tmp_path):
    import download_db

    db_path = tmp_path / "cn" / "redive_cn.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"db")
    calls = []

    monkeypatch.setattr(download_db, "get_db_path", lambda region: db_path)
    monkeypatch.setattr(download_db, "download_database", lambda region: calls.append(region) or str(db_path))

    assert download_db.ensure_database_available("cn", has_update=False) == str(db_path)
    assert calls == []
