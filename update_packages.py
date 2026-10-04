import os
import json
import gzip
import bz2
import tarfile
import tempfile
from datetime import datetime, timezone

# =========================
# 基本配置
# =========================

REPO_URL = "https://kefou667.github.io/repo"

SOURCE_NAME = "kefou"
SOURCE_IDENTIFIER = "com.kefou.repo"
SOURCE_CONTACT = "https://github.com/kefou667"

DEBS_DIR = "debs"
DEPICTIONS_DIR = "depictions"
ICONS_DIR = "icons"

PACKAGES_FILE = "Packages"
PACKAGES_GZ = "Packages.gz"
PACKAGES_BZ2 = "Packages.bz2"

SILEO_JSON = "sileo.json"
NEWS_JSON = "news.json"

MAX_NEWS = 10


# =========================
# 工具
# =========================

def read_control_from_deb(deb_path):
    """
    从 .deb 中读取 DEBIAN/control
    支持 control.tar.gz / control.tar.xz / control.tar / control.tar.bz2
    """

    with tarfile.open(deb_path, mode="r:*") as tar:
        for member in tar.getmembers():
            name = member.name

            if name.endswith("control"):
                extracted = tar.extractfile(member)

                if extracted:
                    data = extracted.read()
                    return data.decode("utf-8", errors="replace")

    return ""


def parse_control(control_text):
    """
    简单解析 Debian control 文件
    """

    data = {}
    current_key = None

    for line in control_text.splitlines():

        if not line.strip():
            continue

        if line[0].isspace():
            if current_key:
                data[current_key] += "\n" + line.strip()
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip()
        value = value.strip()

        data[key] = value
        current_key = key

    return data


def extract_icon_from_deb(deb_path, package_name):
    """
    尝试从 .deb 的 data.tar.* 中自动寻找 PNG 图标。
    """

    try:
        with tarfile.open(deb_path, mode="r:*") as deb:

            members = deb.getmembers()

            data_members = [
                m for m in members
                if "/data.tar" in m.name or m.name.startswith("data.tar")
            ]

            # 某些 Python tarfile 不能直接读取嵌套 tar，
            # 所以先寻找真正的 data.tar 文件。
            for data_member in data_members:

                extracted = deb.extractfile(data_member)

                if not extracted:
                    continue

                with tempfile.NamedTemporaryFile(delete=False) as temp:
                    temp.write(extracted.read())
                    temp_path = temp.name

                try:
                    with tarfile.open(temp_path, mode="r:*") as data_tar:

                        candidates = []

                        for member in data_tar.getmembers():

                            if not member.isfile():
                                continue

                            name = member.name.lower()

                            if not name.endswith(".png"):
                                continue

                            score = 0

                            if ".app/" in name:
                                score += 100

                            if "icon" in name:
                                score += 80

                            if "icon@" in name:
                                score += 20

                            if "120x120" in name:
                                score += 60

                            if "180x180" in name:
                                score += 50

                            if "1024x1024" in name:
                                score += 40

                            candidates.append((score, member))

                        if not candidates:
                            continue

                        candidates.sort(
                            key=lambda x: x[0],
                            reverse=True
                        )

                        _, best_member = candidates[0]

                        icon_data = data_tar.extractfile(best_member)

                        if icon_data:

                            os.makedirs(ICONS_DIR, exist_ok=True)

                            output_path = os.path.join(
                                ICONS_DIR,
                                package_name + ".png"
                            )

                            with open(output_path, "wb") as f:
                                f.write(icon_data.read())

                            print(
                                f"自动提取图标: {package_name}.png"
                            )

                            return output_path

                finally:
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    except Exception as e:
        print(f"图标提取失败 {package_name}: {e}")

    return None


def get_icon(package_name, deb_path):
    """
    图标优先级：

    1. icons/Package.png
    2. 从 .deb 自动提取
    3. icons/default.png
    """

    os.makedirs(ICONS_DIR, exist_ok=True)

    manual_icon = os.path.join(
        ICONS_DIR,
        package_name + ".png"
    )

    if os.path.isfile(manual_icon):
        return manual_icon

    extracted_icon = extract_icon_from_deb(
        deb_path,
        package_name
    )

    if extracted_icon:
        return extracted_icon

    default_icon = os.path.join(
        ICONS_DIR,
        "default.png"
    )

    if os.path.isfile(default_icon):
        return default_icon

    return None


def read_old_packages():
    """
    读取上一次生成的 Packages。
    用来判断：
    - 新增插件
    - 插件版本升级
    """

    if not os.path.isfile(PACKAGES_FILE):
        return {}

    try:
        with open(PACKAGES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    packages = {}

    blocks = content.split("\n\n")

    for block in blocks:

        package = None
        version = None
        name = None

        for line in block.splitlines():

            if line.startswith("Package: "):
                package = line[9:].strip()

            elif line.startswith("Version: "):
                version = line[9:].strip()

            elif line.startswith("Name: "):
                name = line[6:].strip()

        if package:
            packages[package] = {
                "version": version or "",
                "name": name or package
            }

    return packages


def read_news():
    """
    读取已有 news.json。
    """

    if not os.path.isfile(NEWS_JSON):
        return []

    try:
        with open(NEWS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_news(news):
    """
    保存 News。
    """

    news = news[:MAX_NEWS]

    with open(
        NEWS_JSON,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            news,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.write("\n")


# =========================
# 主程序
# =========================

def main():

    os.makedirs(DEBS_DIR, exist_ok=True)
    os.makedirs(DEPICTIONS_DIR, exist_ok=True)
    os.makedirs(ICONS_DIR, exist_ok=True)

    print("读取旧 Packages...")

    old_packages = read_old_packages()

    packages = []

    # =========================
    # 扫描 deb
    # =========================

    for filename in sorted(os.listdir(DEBS_DIR)):

        if not filename.endswith(".deb"):
            continue

        deb_path = os.path.join(
            DEBS_DIR,
            filename
        )

        try:
            control_text = read_control_from_deb(
                deb_path
            )

            control = parse_control(
                control_text
            )

            if not control.get("Package"):
                print(
                    f"跳过无 Package 字段: {filename}"
                )
                continue

            package_name = control["Package"]

            version = control.get(
                "Version",
                ""
            )

            name = control.get(
                "Name",
                package_name
            )

            description = control.get(
                "Description",
                ""
            )

            architecture = control.get(
                "Architecture",
                "iphoneos-arm64"
            )

            maintainer = control.get(
                "Maintainer",
                SOURCE_NAME
            )

            section = control.get(
                "Section",
                "Tweaks"
            )

            author = control.get(
                "Author",
                maintainer
            )

            homepage = control.get(
                "Homepage",
                SOURCE_CONTACT
            )

            icon_path = get_icon(
                package_name,
                deb_path
            )

            if icon_path:
                icon_url = (
                    REPO_URL
                    + "/"
                    + icon_path.replace("\\", "/")
                )
            else:
                icon_url = ""

            depiction_url = (
                f"{REPO_URL}/depictions/"
                f"{package_name}.html"
            )

            sileo_depiction_url = (
                f"{REPO_URL}/depictions/"
                f"{package_name}.json"
            )

            package_data = {
                "Package": package_name,
                "Name": name,
                "Version": version,
                "Architecture": architecture,
                "Description": description,
                "Maintainer": maintainer,
                "Author": author,
                "Section": section,
                "Filename": f"debs/{filename}",
                "Size": os.path.getsize(deb_path),
                "Homepage": homepage,
                "Depiction": depiction_url,
                "Sileodepiction": sileo_depiction_url
            }

            if icon_url:
                package_data["Icon"] = icon_url

            packages.append(package_data)

            # =========================
            # 生成 HTML Depiction
            # =========================

            html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    margin: 0;
    padding: 30px;
    background: #f5f5f7;
    color: #111;
}}
.card {{
    max-width: 700px;
    margin: auto;
    background: white;
    border-radius: 20px;
    padding: 30px;
    box-shadow: 0 8px 30px rgba(0,0,0,.08);
}}
.icon {{
    width: 100px;
    height: 100px;
    border-radius: 22px;
}}
h1 {{
    margin-bottom: 5px;
}}
.version {{
    color: #777;
}}
.description {{
    margin-top: 25px;
    white-space: pre-wrap;
}}
</style>
</head>

<body>

<div class="card">

{"<img class='icon' src='" + icon_url + "'>" if icon_url else ""}

<h1>{name}</h1>

<div class="version">
版本 {version}
</div>

<div class="description">
{description}
</div>

</div>

</body>
</html>
"""

            with open(
                os.path.join(
                    DEPICTIONS_DIR,
                    package_name + ".html"
                ),
                "w",
                encoding="utf-8"
            ) as f:
                f.write(html)

            # =========================
            # Sileo Native Depiction
            # =========================

            depiction_json = {
                "class": "DepictionTabView",
                "tintColor": "#007AFF",
                "tabs": [
                    {
                        "tabname": "详情",
                        "views": [
                            {
                                "class": "DepictionMarkdownView",
                                "markdown": (
                                    f"# {name}\n\n"
                                    f"{description}"
                                )
                            },
                            {
                                "class": "DepictionTableTextView",
                                "title": "版本",
                                "text": version
                            }
                        ]
                    }
                ]
            }

            with open(
                os.path.join(
                    DEPICTIONS_DIR,
                    package_name + ".json"
                ),
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    depiction_json,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:

            print(
                f"处理 {filename} 失败: {e}"
            )

    # =========================
    # Packages
    # =========================

    packages.sort(
        key=lambda x: x["Package"]
    )

    lines = []

    for pkg in packages:

        for key, value in pkg.items():

            if value is None:
                continue

            lines.append(
                f"{key}: {value}"
            )

        lines.append("")

    packages_text = "\n".join(lines)

    with open(
        PACKAGES_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(packages_text)

    with open(
        PACKAGES_GZ,
        "wb"
    ) as f:

        f.write(
            gzip.compress(
                packages_text.encode("utf-8")
            )
        )

    with open(
        PACKAGES_BZ2,
        "wb"
    ) as f:

        f.write(
            bz2.compress(
                packages_text.encode("utf-8")
            )
        )

    print("Packages 已生成")

    # =========================
    # sileo.json
    # =========================

    sileo_packages = []

    for pkg in packages:

        sileo_packages.append({
            "name": pkg["Name"],
            "identifier": pkg["Package"],
            "version": pkg["Version"],
            "description": pkg["Description"],
            "section": pkg["Section"]
        })

    sileo_data = {
        "name": SOURCE_NAME,
        "identifier": SOURCE_IDENTIFIER,
        "url": REPO_URL,
        "version": "1.0",
        "contact": SOURCE_CONTACT,
        "packages": sileo_packages
    }

    with open(
        SILEO_JSON,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sileo_data,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.write("\n")

    print("sileo.json 已生成")

    # =========================
    # 自动 News
    # =========================

    current_packages = {}

    for pkg in packages:

        current_packages[pkg["Package"]] = {
            "version": pkg["Version"],
            "name": pkg["Name"]
        }

    news = read_news()

    today = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")

    new_news = []

    for package_id, current in current_packages.items():

        old = old_packages.get(
            package_id
        )

        # 新插件
        if old is None:

            new_news.append({
                "title": f"新增插件：{current['name']}",
                "subtitle": (
                    f"版本 {current['version']}"
                ),
                "date": today,
                "url": (
                    f"{REPO_URL}/depictions/"
                    f"{package_id}.html"
                )
            })

            print(
                f"News：发现新插件 {package_id}"
            )

        # 版本升级
        elif old.get("version") != current["version"]:

            new_news.append({
                "title": (
                    f"更新插件：{current['name']}"
                ),
                "subtitle": (
                    f"{old.get('version', '')} → "
                    f"{current['version']}"
                ),
                "date": today,
                "url": (
                    f"{REPO_URL}/depictions/"
                    f"{package_id}.html"
                )
            })

            print(
                f"News：发现版本更新 {package_id}"
            )

    # 新消息放最前面
    news = new_news + news

    # 最多保留 10 条
    news = news[:MAX_NEWS]

    save_news(news)

    print(
        f"News 已更新，共 {len(news)} 条"
    )

    print("")
    print("================================")
    print("源索引生成完成")
    print("================================")


if __name__ == "__main__":
    main()
