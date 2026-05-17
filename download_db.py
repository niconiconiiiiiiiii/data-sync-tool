import urllib.request
import os
import re
import sqlite3
import brotli
import requests

def load_local_version(region):
    filename = f"{region.upper()}_pcr_data.py"
    if not os.path.exists(filename):
        return None
    version = None
    db_hash = None
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^TRUTH_VERSION\s*=\s*"(.+)"', line)
            if m:
                version = m.group(1)
            m = re.match(r'^DB_HASH\s*=\s*"(.+)"', line)
            if m:
                db_hash = m.group(1)
    if version and db_hash:
        return {'truthVersion': version, 'hash': db_hash}
    return None

def check_db_version(region):
    url = "https://wthee.xyz/pcr/api/v1/db/info/v2"
    payload = {"regionCode": region}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  获取 {region.upper()} 版本信息失败: {e}")
        return None

def get_db_path(region):
    return os.path.join(region, f"redive_{region}.db")

def check_update(region):
    remote_info = check_db_version(region)
    if not remote_info or remote_info.get("status") != 0:
        return False, None, None

    remote_version = remote_info['data']['truthVersion']
    remote_hash = remote_info['data']['hash']

    local_info = load_local_version(region)
    if local_info is None:
        return True, remote_version, remote_hash

    local_version = local_info.get('truthVersion')
    local_hash = local_info.get('hash')

    if local_version != remote_version or local_hash != remote_hash:
        return True, remote_version, remote_hash

    return False, remote_version, remote_hash

def download_database(region):
    db_url = f"https://wthee.xyz/db/redive_{region}.db.br"
    db_path = get_db_path(region)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    temp_path = db_path + ".br"

    try:
        print(f"  正在下载: {db_url}")
        urllib.request.urlretrieve(db_url, temp_path)
        print(f"  下载完成，正在解压...")

        with open(temp_path, 'rb') as f:
            decompressed_data = brotli.decompress(f.read())
        with open(db_path, 'wb') as f:
            f.write(decompressed_data)
        os.remove(temp_path)
        print(f"  解压完成: {db_path}")
        return db_path

    except Exception as e:
        print(f"  下载失败: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None

def extract_unit_data(db_path, region):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 根据地区设置不同的提取范围
    if region in ['jp', 'tw']:
        # JP, TW: 100101-169999, 180101-189999
        where_clause = "(unit_id BETWEEN 100101 AND 169999) OR (unit_id BETWEEN 180101 AND 189999)"
    elif region == 'cn':
        # CN: 100101-170201, 180101-189999
        where_clause = "(unit_id BETWEEN 100101 AND 170201) OR (unit_id BETWEEN 180101 AND 189999)"
    else:
        # 默认: 100101-189901
        where_clause = "unit_id BETWEEN 100101 AND 189901"

    query1 = f"""
        SELECT unit_id, unit_name, search_area_width
        FROM unit_data
        WHERE {where_clause}
        ORDER BY unit_id
    """
    cursor.execute(query1)
    unit_data = {row[0]: {'unit_name': row[1], 'search_area_width': row[2]} for row in cursor.fetchall()}

    query2 = f"""
        SELECT unit_id, unit_role_id
        FROM unit_role_data
        WHERE {where_clause}
        ORDER BY unit_id
    """
    cursor.execute(query2)
    role_data = {row[0]: row[1] for row in cursor.fetchall()}

    query3 = f"""
        SELECT unit_id, talent_id
        FROM unit_talent
        WHERE {where_clause}
        ORDER BY unit_id
    """
    cursor.execute(query3)
    talent_data = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    unavailable = {}
    unit_name = {}
    search_area_width = {}
    unit_role_id = {}
    talent_id = {}

    for uid in sorted(unit_data.keys()):
        converted_id = uid // 100
        role = role_data.get(uid)
        talent = talent_data.get(uid)
        name = unit_data[uid]['unit_name']

        if role is None or talent is None:
            unavailable[converted_id] = name
        else:
            unit_name[converted_id] = name
            search_area_width[converted_id] = unit_data[uid]['search_area_width']
            unit_role_id[converted_id] = role
            talent_id[converted_id] = talent

    return {
        'unavailable': unavailable,
        'unit_name': unit_name,
        'search_area_width': search_area_width,
        'unit_role_id': unit_role_id,
        'talent_id': talent_id
    }

def save_to_py(data, region, version, db_hash):
    filename = f"{region.upper()}_pcr_data.py"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("'''公主连接Re:dive的游戏数据'''\n\n")
        f.write(f'TRUTH_VERSION = "{version}"\n')
        f.write(f'DB_HASH = "{db_hash}"\n\n')

        f.write("UnavailableChara = {\n")
        for uid in sorted(data['unavailable'].keys()):
            name = data['unavailable'][uid]
            f.write(f"    {uid},   # {name}\n")
        f.write("}\n\n")

        f.write("UNIT_NAME = {\n")
        for uid in sorted(data['unit_name'].keys()):
            f.write(f"    {uid}: \"{data['unit_name'][uid]}\",\n")
        f.write("}\n\n")

        f.write("SEARCH_AREA_WIDTH = {\n")
        for uid in sorted(data['search_area_width'].keys()):
            f.write(f"    {uid}: {data['search_area_width'][uid]},\n")
        f.write("}\n\n")

        f.write("UNIT_ROLE_ID = {\n")
        for uid in sorted(data['unit_role_id'].keys()):
            f.write(f"    {uid}: {data['unit_role_id'][uid]},\n")
        f.write("}\n\n")

        f.write("TALENT_ID = {\n")
        for uid in sorted(data['talent_id'].keys()):
            f.write(f"    {uid}: {data['talent_id'][uid]},\n")
        f.write("}\n")

    print(f"  数据已保存到 {filename}")
    print(f"  - 有效角色: {len(data['unit_name'])} 个")
    print(f"  - 不可用角色: {len(data['unavailable'])} 个")
    return filename

def main():
    print("=" * 60)
    print("PCR 数据库版本检测、下载与数据提取工具")
    print("=" * 60)

    regions = ['jp', 'cn', 'tw']

    print("\n[步骤1] 检查版本更新...")
    update_info = {}

    for region in regions:
        has_update, remote_version, remote_hash = check_update(region)
        update_info[region] = {
            'has_update': has_update,
            'version': remote_version,
            'hash': remote_hash
        }
        if has_update:
            print(f"  {region.upper()}: 检测到更新 -> {remote_version}")
        elif remote_version:
            print(f"  {region.upper()}: 已是最新版本 -> {remote_version}")
        else:
            print(f"  {region.upper()}: 版本检查失败")

    print("\n[步骤2] 下载/更新数据库...")

    for region in regions:
        info = update_info[region]
        if info['has_update']:
            print(f"\n  >>> {region.upper()} 需要更新:")
            db_path = download_database(region)
            if db_path:
                data = extract_unit_data(db_path, region)
                save_to_py(data, region, info['version'], info['hash'])
        else:
            if info['version']:
                print(f"  {region.upper()}: 已是最新，跳过")
            else:
                print(f"  {region.upper()}: 跳过（版本检查失败）")

    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()