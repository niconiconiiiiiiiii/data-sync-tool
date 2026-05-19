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
    assert normalize_alias(" \uff35\uff25 ") == "ue"


def test_build_pack_outputs_v2_slim_units_and_aliases_json(tmp_path):
    cn = write_module(
        tmp_path / "CN_pcr_data.py",
        '''
TRUTH_VERSION = "cnv1"
DB_HASH = "cnhash"
UnavailableChara = {1003}
UNIT_NAME = {1001: "\u65e5\u548c\u8389", 1002: "\u4f18\u8863", 1003: "\u601c"}
SEARCH_AREA_WIDTH = {1001: 200, 1002: 0, 1003: 300}
UNIT_ROLE_ID = {1001: 1, 1002: 6, 1003: 2}
TALENT_ID = {1001: 1, 1002: 4, 1003: 3}
''',
    )
    jp = write_module(
        tmp_path / "JP_pcr_data.py",
        '''
TRUTH_VERSION = "jpv1"
DB_HASH = "jphash"
UnavailableChara = set()
UNIT_NAME = {1001: "\u30d2\u30e8\u30ea", 1002: "\u30e6\u30a4", 1702: "CN Only Range", 1800: "EX"}
SEARCH_AREA_WIDTH = {1001: 210, 1002: 800, 1702: 500, 1800: 600}
UNIT_ROLE_ID = {1001: 9, 1002: 6, 1702: 7, 1800: 8}
TALENT_ID = {1001: 9, 1002: 4, 1702: 5, 1800: 2}
''',
    )
    nick = write_module(
        tmp_path / "_pcr_data.py",
        '''
UnavailableChara = {1072}
CHARA_NICKNAME = {1001: "\u732b\u62f3", 1002: "u1", 1003: "\u5251\u5723", 1072: "\u53ef\u841d\u7239", 1702: "\u56fd\u670d\u8fb9\u754c", 1800: "\u7279\u6b8a\u8fb9\u754c"}
CHARA_NAME = {
    1001: ["\u65e5\u548c", "\u30d2\u30e8\u30ea", "Hiyori", "\u65e5\u548c\u8389", "\u732b\u62f3"],
    1002: ["\u4f18\u8863", "\u30e6\u30a4", "Yui", "\u7531\u8863", "ue", "\uff35\uff25"],
    1003: ["\u601c"],
    1072: ["\u53ef\u841d\u7239"],
    1702: ["\u56fd\u670d\u8fb9\u754c"],
    1800: ["\u7279\u6b8a\u8fb9\u754c"],
}
''',
    )

    pack_path = build_pack(cn_path=cn, jp_path=jp, nickname_path=nick, output_dir=tmp_path / "dist", generated_at="2026-05-19T00:00:00Z")

    manifest = read_json_from_zip(pack_path, "manifest.json")
    units = read_json_from_zip(pack_path, "units.json")
    aliases = read_json_from_zip(pack_path, "aliases.json")
    checksums = read_json_from_zip(pack_path, "checksums.json")

    assert manifest["schema_version"] == 2
    assert units["schema_version"] == 2
    assert aliases["schema_version"] == 2
    assert checksums["schema_version"] == 2
    assert manifest["pack_version"] == "cn-cnv1-nick-local"

    hiyori = units["units"]["1001"]
    assert hiyori == {
        "unit_id": 1001,
        "display_nickname": "\u732b\u62f3",
        "search_area_width": 200,
        "unit_role_id": 1,
        "talent_id": 1,
    }
    assert "battle_unit_id" not in hiyori
    assert "cn_unit_name" not in hiyori
    assert "jp_unit_name" not in hiyori
    assert "aliases" not in hiyori
    assert "field_sources" not in hiyori

    yui = units["units"]["1002"]
    assert yui["display_nickname"] == "u1"
    assert yui["search_area_width"] == 800
    assert yui["unit_role_id"] == 6
    assert yui["talent_id"] == 4

    assert "1003" not in units["units"]
    assert "1072" not in units["units"]
    assert units["units"]["1702"]["display_nickname"] == "\u56fd\u670d\u8fb9\u754c"
    assert units["units"]["1800"]["display_nickname"] == "\u7279\u6b8a\u8fb9\u754c"

    assert aliases["aliases"]["\u732b\u62f3"] == 1001
    assert aliases["aliases"]["\u65e5\u548c\u8389"] == 1001
    assert aliases["aliases"]["ue"] == 1002
    assert aliases["conflicts"] == []

    with zipfile.ZipFile(pack_path) as zf:
        assert msgpack.unpackb(zf.read("vision_templates.msgpack"), raw=False) == {"schema_version": 2, "templates": {}}
        for filename, digest in checksums["files"].items():
            assert hashlib.sha256(zf.read(filename)).hexdigest() == digest


def test_build_pack_filters_out_of_range_and_unknown_unit_1000(tmp_path):
    cn = write_module(
        tmp_path / "CN_pcr_data.py",
        '''
TRUTH_VERSION = "cnv1"
DB_HASH = "cnhash"
UnavailableChara = set()
UNIT_NAME = {1000: "\u672a\u77e5\u89d2\u8272", 1703: "\u8d8a\u754c", 1899: "\u6709\u6548", 1900: "\u8d8a\u754c"}
SEARCH_AREA_WIDTH = {1000: 1, 1703: 1, 1899: 1, 1900: 1}
UNIT_ROLE_ID = {1000: 1, 1703: 1, 1899: 1, 1900: 1}
TALENT_ID = {1000: 1, 1703: 1, 1899: 1, 1900: 1}
''',
    )
    jp = write_module(
        tmp_path / "JP_pcr_data.py",
        '''
TRUTH_VERSION = "jpv1"
DB_HASH = "jphash"
UnavailableChara = set()
UNIT_NAME = {}
SEARCH_AREA_WIDTH = {}
UNIT_ROLE_ID = {}
TALENT_ID = {}
''',
    )
    nick = write_module(
        tmp_path / "_pcr_data.py",
        '''
UnavailableChara = set()
CHARA_NICKNAME = {1000: "\u672a\u77e5", 1703: "\u8d8a\u754c", 1899: "\u6709\u6548", 1900: "\u8d8a\u754c"}
CHARA_NAME = {1000: ["\u672a\u77e5"], 1703: ["\u8d8a\u754c"], 1899: ["\u6709\u6548"], 1900: ["\u8d8a\u754c"]}
''',
    )

    pack_path = build_pack(cn_path=cn, jp_path=jp, nickname_path=nick, output_dir=tmp_path / "dist", generated_at="2026-05-19T00:00:00Z")
    units = read_json_from_zip(pack_path, "units.json")["units"]
    aliases = read_json_from_zip(pack_path, "aliases.json")["aliases"]

    assert sorted(units.keys()) == ["1899"]
    assert aliases == {"\u6709\u6548": 1899}


def test_build_pack_reports_alias_conflicts_and_keeps_first_owner(tmp_path):
    cn = write_module(
        tmp_path / "CN_pcr_data.py",
        '''
TRUTH_VERSION = "cnv1"
DB_HASH = "cnhash"
UnavailableChara = set()
UNIT_NAME = {1001: "\u65e5\u548c\u8389", 1002: "\u4f18\u8863"}
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
UnavailableChara = set()
UNIT_NAME = {}
SEARCH_AREA_WIDTH = {}
UNIT_ROLE_ID = {}
TALENT_ID = {}
''',
    )
    nick = write_module(
        tmp_path / "_pcr_data.py",
        '''
UnavailableChara = set()
CHARA_NICKNAME = {1001: "\u732b\u62f3", 1002: "u1"}
CHARA_NAME = {1001: ["\u51b2\u7a81"], 1002: ["\u51b2\u7a81"]}
''',
    )

    pack_path = build_pack(cn_path=cn, jp_path=jp, nickname_path=nick, output_dir=tmp_path / "dist", generated_at="2026-05-19T00:00:00Z")
    aliases = read_json_from_zip(pack_path, "aliases.json")

    assert aliases["aliases"]["\u51b2\u7a81"] == 1001
    assert aliases["conflicts"] == [
        {
            "alias": "\u51b2\u7a81",
            "kept_unit_id": 1001,
            "dropped_unit_id": 1002,
            "dropped_value": "\u51b2\u7a81",
        }
    ]
