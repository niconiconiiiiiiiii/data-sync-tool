import hashlib
import json
import zipfile

import msgpack

from build_jjc_pack import build_pack, normalize_alias


def write_module(path, body):
    path.write_text(body, encoding="utf-8")
    return path


def read_json_from_zip(zip_path, name):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read(name).decode("utf-8"))


def test_normalize_alias_uses_nfkc_casefold_and_trim():
    assert normalize_alias(" ＵＥ ") == "ue"


def test_build_pack_uses_cn_first_jp_fallback_and_nickname_sources(tmp_path):
    cn = write_module(
        tmp_path / "CN_pcr_data.py",
        '''
TRUTH_VERSION = "cnv1"
DB_HASH = "cnhash"
UnavailableChara = {1002}
UNIT_NAME = {1001: "日和莉", 1002: "优衣"}
SEARCH_AREA_WIDTH = {1001: 200}
UNIT_ROLE_ID = {1001: 1}
TALENT_ID = {1001: 1}
''',
    )
    jp = write_module(
        tmp_path / "JP_pcr_data.py",
        '''
TRUTH_VERSION = "jpv1"
DB_HASH = "jphash"
UnavailableChara = {}
UNIT_NAME = {1001: "ヒヨリ", 1002: "ユイ"}
SEARCH_AREA_WIDTH = {1001: 210, 1002: 800}
UNIT_ROLE_ID = {1001: 9, 1002: 6}
TALENT_ID = {1001: 9, 1002: 4}
''',
    )
    nick = write_module(
        tmp_path / "_pcr_data.py",
        '''
CHARA_NICKNAME = {1001: "日和", 1002: "优衣"}
CHARA_NAME = {1001: ["日和莉", "猫拳"], 1002: ["由衣", "ＵＥ"]}
''',
    )

    pack_path = build_pack(cn_path=cn, jp_path=jp, nickname_path=nick, output_dir=tmp_path / "dist", generated_at="2026-05-19T00:00:00Z")

    manifest = read_json_from_zip(pack_path, "manifest.json")
    units = read_json_from_zip(pack_path, "units.json")
    aliases = read_json_from_zip(pack_path, "aliases.json")
    checksums = read_json_from_zip(pack_path, "checksums.json")

    assert manifest["schema_version"] == 1
    assert manifest["pack_version"] == "cn-cnv1-nick-local"
    assert manifest["sources"]["cn"]["truth_version"] == "cnv1"
    assert manifest["sources"]["jp"]["truth_version"] == "jpv1"

    hiyori = units["units"]["1001"]
    assert hiyori["display_nickname"] == "日和"
    assert hiyori["cn_unit_name"] == "日和莉"
    assert hiyori["search_area_width"] == 200
    assert hiyori["unit_role_id"] == 1
    assert hiyori["talent_id"] == 1
    assert hiyori["field_sources"]["search_area_width"] == "cn"

    yui = units["units"]["1002"]
    assert yui["display_nickname"] == "优衣"
    assert yui["cn_unit_name"] == "优衣"
    assert yui["search_area_width"] == 800
    assert yui["unit_role_id"] == 6
    assert yui["talent_id"] == 4
    assert yui["field_sources"]["search_area_width"] == "jp"

    assert aliases["aliases"]["日和莉"] == 1001
    assert aliases["aliases"]["猫拳"] == 1001
    assert aliases["aliases"]["ue"] == 1002
    assert aliases["conflicts"] == []

    with zipfile.ZipFile(pack_path) as zf:
        assert msgpack.unpackb(zf.read("vision_templates.msgpack"), raw=False) == {"schema_version": 1, "templates": {}}
        for filename, digest in checksums["files"].items():
            assert hashlib.sha256(zf.read(filename)).hexdigest() == digest


def test_build_pack_reports_alias_conflicts_and_keeps_first_owner(tmp_path):
    cn = write_module(
        tmp_path / "CN_pcr_data.py",
        '''
TRUTH_VERSION = "cnv1"
DB_HASH = "cnhash"
UnavailableChara = {}
UNIT_NAME = {1001: "日和莉", 1002: "优衣"}
SEARCH_AREA_WIDTH = {1001: 200, 1002: 800}
UNIT_ROLE_ID = {1001: 1, 1002: 6}
TALENT_ID = {1001: 1, 1002: 4}
''',
    )
    jp = write_module(
        tmp_path / "JP_pcr_data.py",
        '''
TRUTH_VERSION = "jpv1"
DB_HASH = "jphash"
UnavailableChara = {}
UNIT_NAME = {}
SEARCH_AREA_WIDTH = {}
UNIT_ROLE_ID = {}
TALENT_ID = {}
''',
    )
    nick = write_module(
        tmp_path / "_pcr_data.py",
        '''
CHARA_NICKNAME = {1001: "日和", 1002: "优衣"}
CHARA_NAME = {1001: ["猫拳"], 1002: ["猫拳"]}
''',
    )

    pack_path = build_pack(cn_path=cn, jp_path=jp, nickname_path=nick, output_dir=tmp_path / "dist", generated_at="2026-05-19T00:00:00Z")
    aliases = read_json_from_zip(pack_path, "aliases.json")

    assert aliases["aliases"]["猫拳"] == 1001
    assert aliases["conflicts"] == [
        {
            "alias": "猫拳",
            "kept_unit_id": 1001,
            "dropped_unit_id": 1002,
            "dropped_value": "猫拳",
        }
    ]
