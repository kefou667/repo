#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
kefou Sileo/APT Packages 生成器

功能：
- 无需 dpkg-deb
- 支持 control.tar.gz / control.tar.xz / control.tar
- 生成 Packages / Packages.gz / Packages.bz2
- 自动生成 HTML / JSON Depiction
- 自动生成 sileo.json
- 混合图标方案：
    1. 优先使用 icons/<Package>.png
    2. 没有则尝试从 .deb 中的 .app 提取 PNG
    3. 都没有则使用 icons/default.png
"""

import bz2
import gzip
import hashlib
import html
import io
import json
import lzma
import tarfile
from pathlib import Path


# ============================================================
# 基本配置
# ============================================================

REPO_URL = "https://kefou667.github.io/repo"

SOURCE_NAME = "kefou"
SOURCE_IDENTIFIER = "com.kefou.repo"
SOURCE_CONTACT = "https://github.com/kefou667"


ROOT = Path(__file__).resolve().parent

DEBS = ROOT / "debs"
DEPICTIONS = ROOT / "depictions"
ICONS = ROOT / "icons"


# ============================================================
# control 字段
# ============================================================

FIELDS = [
    "Package",
    "Name",
    "Version",
    "Architecture",
    "Description",
    "Maintainer",
    "Author",
    "Section",
    "Depends",
    "Pre-Depends",
    "Recommends",
    "Conflicts",
    "Provides",
    "Replaces",
    "Icon",
    "Filename",
    "Size",
]


# ============================================================
# 读取 .deb
# ============================================================

def read_deb_members(path: Path):
    """
    读取 Debian ar 格式的 .deb
    """

    raw = path.read_bytes()

    if not raw.startswith(b"!<arch>\n"):
        raise ValueError("不是标准 .deb/ar 文件")

    pos = 8

    while pos + 60 <= len(raw):

        hdr = raw[pos:pos + 60]

        if hdr[58:60] != b"`\n":
            break

        name = (
            hdr[0:16]
            .rstrip(b" /")
            .decode("ascii", "replace")
            .strip()
        )

        try:
            size = int(hdr[48:58].strip())
        except ValueError:
            break

        data_start = pos + 60
        member = raw[data_start:data_start + size]

        yield name, member

        pos = data_start + size + (size & 1)


# ============================================================
# 读取 control
# ============================================================

def read_control_from_deb(path: Path) -> dict:

    for name, member in read_deb_members(path):

        if name not in (
            "control.tar.gz",
            "control.tar.xz",
            "control.tar"
        ):
            continue

        if name.endswith(".gz"):
            tar_data = gzip.decompress(member)

        elif name.endswith(".xz"):
            tar_data = lzma.decompress(member)

        else:
            tar_data = member

        with tarfile.open(
            fileobj=io.BytesIO(tar_data),
            mode="r:"
        ) as tar:

            control_file = None

            try:
                control_file = tar.extractfile("./control")
            except KeyError:
                pass

            if control_file is None:

                try:
                    control_file = tar.extractfile("control")
                except KeyError:
                    pass

            if control_file is None:

                for m in tar.getmembers():

                    if (
                        m.name.rstrip("/").endswith("/control")
                        or m.name == "control"
                    ):
                        control_file = tar.extractfile(m)
                        break

            if control_file is None:
                raise ValueError(
                    "control.tar 中找不到 control"
                )

            text = control_file.read().decode(
                "utf-8",
                "replace"
            )

        info = {}

        current_key = None

        for line in text.splitlines():

            # 多行字段
            if line.startswith((" ", "\t")) and current_key:

                info[current_key] += "\n" + line.strip()

                continue

            if ":" not in line:
                continue

            k, v = line.split(":", 1)

            k = k.strip()
            v = v.strip()

            current_key = k

            if k in FIELDS:
                info[k] = v

        return info

    raise ValueError(
        "找不到 control.tar.*"
    )


# ============================================================
# Hash
# ============================================================

def digest(path, algorithm):

    h = hashlib.new(algorithm)

    with open(path, "rb") as f:

        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b""
        ):
            h.update(chunk)

    return h.hexdigest()


# ============================================================
# 工具
# ============================================================

def safe_package_name(package):

    return package.replace("/", "_")


# ============================================================
# 混合图标系统
# ============================================================

def find_icon(package, deb_path):

    """
    图标优先级：

    1. icons/<Package>.png
    2. 从 .deb 中尝试寻找 .app PNG
    3. icons/default.png
    """

    ICONS.mkdir(exist_ok=True)

    # --------------------------------------------------------
    # 方案 A：手动图标
    # --------------------------------------------------------

    manual_icon = ICONS / f"{package}.png"

    if manual_icon.exists():

        print(
            f"🎨 使用手动图标: "
            f"{manual_icon.name}"
        )

        return f"{REPO_URL}/icons/{manual_icon.name}"


    # --------------------------------------------------------
    # 方案 B：从 .deb 自动提取
    # --------------------------------------------------------

    extracted_icon = ICONS / f"{package}.png"

    try:

        for name, member in read_deb_members(deb_path):

            if not name.startswith("data.tar"):
                continue

            # 解压 data.tar
            if name.endswith(".gz"):

                tar_data = gzip.decompress(member)

            elif name.endswith(".xz"):

                tar_data = lzma.decompress(member)

            elif name.endswith(".bz2"):

                tar_data = bz2.decompress(member)

            else:

                tar_data = member

            with tarfile.open(
                fileobj=io.BytesIO(tar_data),
                mode="r:"
            ) as tar:

                candidates = []

                for m in tar.getmembers():

                    if not m.isfile():
                        continue

                    filename = m.name.lower()

                    if not filename.endswith(".png"):
                        continue

                    score = 0

                    # .app 中的图片优先
                    if ".app/" in filename:
                        score += 50

                    # icon 名称优先
                    if "icon" in filename:
                        score += 30

                    # 常见 AppIcon 尺寸
                    if (
                        "60x60" in filename
                        or "120x120" in filename
                        or "180x180" in filename
                    ):
                        score += 20

                    candidates.append(
                        (score, m.name, m)
                    )

                if candidates:

                    candidates.sort(
                        key=lambda x: (
                            -x[0],
                            x[1]
                        )
                    )

                    _, chosen_name, chosen = candidates[0]

                    source = tar.extractfile(chosen)

                    if source:

                        extracted_icon.write_bytes(
                            source.read()
                        )

                        print(
                            f"🎨 自动提取图标: "
                            f"{chosen_name}"
                        )

                        return (
                            f"{REPO_URL}/icons/"
                            f"{extracted_icon.name}"
                        )

    except Exception as e:

        print(
            f"⚠️ 自动提取图标失败 "
            f"{package}: {e}"
        )


    # --------------------------------------------------------
    # 方案 C：默认图标
    # --------------------------------------------------------

    default_icon = ICONS / "default.png"

    if default_icon.exists():

        print(
            f"🎨 使用默认图标: "
            f"default.png"
        )

        return (
            f"{REPO_URL}/icons/"
            f"default.png"
        )


    # 没有任何图标
    print(
        f"⚠️ {package}: "
        f"没有找到图标"
    )

    return ""


# ============================================================
# Depiction
# ============================================================

def write_depictions(info, icon_url):

    package = info.get(
        "Package",
        "unknown"
    )

    safe = safe_package_name(package)

    name = info.get(
        "Name",
        package
    )

    version = info.get(
        "Version",
        ""
    )

    arch = info.get(
        "Architecture",
        ""
    )

    desc = info.get(
        "Description",
        "暂无描述"
    )

    author = (
        info.get("Author")
        or info.get("Maintainer")
        or "未知"
    )

    section = info.get(
        "Section",
        "Tweaks"
    )


    # ========================================================
    # JSON Depiction
    # ========================================================

    depiction_json = {

        "class": "DepictionTabView",

        "minVersion": "0.3",

        "tabs": [

            {

                "class": "DepictionStackView",

                "tabname": "描述",

                "views": [

                    {
                        "class":
                            "DepictionHeaderView",

                        "title": name,

                        "useBoldText": True
                    },

                    {
                        "class":
                            "DepictionMarkdownView",

                        "markdown":
                            f"## {name}\n\n{desc}",

                        "useSpacing": True
                    },

                    {
                        "class":
                            "DepictionSeparatorView"
                    },

                    {
                        "class":
                            "DepictionHeaderView",

                        "title": "信息",

                        "useBoldText": True
                    },

                    {
                        "class":
                            "DepictionTableTextView",

                        "title": "作者",

                        "text": author
                    },

                    {
                        "class":
                            "DepictionTableTextView",

                        "title": "版本",

                        "text": version
                    },

                    {
                        "class":
                            "DepictionTableTextView",

                        "title": "架构",

                        "text": arch
                    },

                    {
                        "class":
                            "DepictionTableTextView",

                        "title": "分类",

                        "text": section
                    }

                ]
            }
        ]
    }


    (
        DEPICTIONS /
        f"{safe}.json"
    ).write_text(

        json.dumps(
            depiction_json,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


    # ========================================================
    # HTML Depiction
    # ========================================================

    h = html.escape

    icon_html = ""

    if icon_url:

        icon_html = f"""
<img
src="{h(icon_url)}"
style="
width:80px;
height:80px;
border-radius:18px;
object-fit:cover;
margin-bottom:15px;
">
"""


    html_doc = f"""<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>{h(name)}</title>

<style>

body {{
font-family:
-apple-system,
BlinkMacSystemFont,
sans-serif;

margin:0;

padding:24px;

background:#f2f2f7;

color:#1c1c1e;
}}

.card {{

max-width:680px;

margin:auto;

background:white;

border-radius:20px;

padding:24px;

box-shadow:
0 4px 20px #0001;

}}

.icon {{

width:80px;

height:80px;

border-radius:18px;

}}

h1 {{

margin-top:8px;

margin-bottom:10px;

}}

.desc {{

line-height:1.6;

color:#444;

}}

.meta {{

display:grid;

grid-template-columns:
100px 1fr;

gap:10px 12px;

color:#555;

}}

hr {{

border:0;

border-top:
1px solid #eee;

margin:20px 0;

}}

</style>

</head>

<body>

<div class="card">

{icon_html}

<h1>{h(name)}</h1>

<div class="desc">

{h(desc).replace(chr(10), "<br>")}

</div>

<hr>

<div class="meta">

<div>版本</div>
<div>{h(version)}</div>

<div>架构</div>
<div>{h(arch)}</div>

<div>作者</div>
<div>{h(author)}</div>

<div>分类</div>
<div>{h(section)}</div>

</div>

</div>

</body>

</html>
"""


    (
        DEPICTIONS /
        f"{safe}.html"
    ).write_text(
        html_doc,
        encoding="utf-8"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    DEBS.mkdir(exist_ok=True)

    DEPICTIONS.mkdir(exist_ok=True)

    ICONS.mkdir(exist_ok=True)


    entries = []

    sileo_packages = []


    # ========================================================
    # 扫描 deb
    # ========================================================

    for deb in sorted(
        DEBS.glob("*.deb")
    ):

        try:

            info = read_control_from_deb(
                deb
            )


            package = info.get(
                "Package"
            )

            version = info.get(
                "Version"
            )

            arch = info.get(
                "Architecture"
            )


            if not package:
                raise ValueError(
                    "缺少 Package"
                )

            if not version:
                raise ValueError(
                    "缺少 Version"
                )

            if not arch:
                raise ValueError(
                    "缺少 Architecture"
                )


            # =================================================
            # rootless 架构提醒
            # =================================================

            if arch not in (
                "iphoneos-arm64",
                "iphoneos-arm64e",
                "all",
                "any"
            ):

                print(
                    f"⚠️ {deb.name}: "
                    f"Architecture={arch}，"
                    f"请确认是否适合 rootless"
                )


            # =================================================
            # 文件信息
            # =================================================

            info["Filename"] = (
                f"debs/{deb.name}"
            )

            info["Size"] = str(
                deb.stat().st_size
            )


            # =================================================
            # 图标
            # =================================================

            icon_url = find_icon(
                package,
                deb
            )

            if icon_url:

                info["Icon"] = icon_url


            # =================================================
            # Depiction
            # =================================================

            write_depictions(
                info,
                icon_url
            )


            stem = safe_package_name(
                package
            )


            info["Depiction"] = (
                f"{REPO_URL}/"
                f"depictions/"
                f"{stem}.html"
            )


            info["Sileodepiction"] = (
                f"{REPO_URL}/"
                f"depictions/"
                f"{stem}.json"
            )


            info["MD5sum"] = digest(
                deb,
                "md5"
            )

            info["SHA256"] = digest(
                deb,
                "sha256"
            )


            entries.append(info)


            # =================================================
            # sileo.json
            # =================================================

            description = info.get(
                "Description",
                ""
            )

            # Sileo 页面通常只需要首行简介
            short_description = (
                description
                .split("\n")[0]
                .strip()
            )


            author = (
                info.get("Author")
                or info.get("Maintainer")
                or "未知"
            )


            sileo_entry = {

                "name":
                    info.get(
                        "Name",
                        package
                    ),

                "package":
                    package,

                "version":
                    version,

                "description":
                    short_description,

                "section":
                    info.get(
                        "Section",
                        ""
                    ),

                "author": {
                    "name":
                        author
                },

                "depiction":
                    info["Depiction"]
            }


            if icon_url:

                sileo_entry["icon"] = (
                    icon_url
                )


            sileo_packages.append(
                sileo_entry
            )


            print(
                f"✅ {deb.name} "
                f"[{package} "
                f"{version} "
                f"{arch}]"
            )


        except Exception as e:

            print(
                f"⚠️ 跳过 "
                f"{deb.name}: {e}"
            )


    # ========================================================
    # Packages
    # ========================================================

    lines = []


    output_fields = [

        "Package",
        "Name",
        "Version",
        "Architecture",
        "Description",

        "Maintainer",
        "Author",

        "Depiction",
        "Sileodepiction",

        "Section",

        "Depends",
        "Pre-Depends",
        "Recommends",

        "Conflicts",
        "Provides",
        "Replaces",

        "Icon",

        "Filename",
        "Size",

        "MD5sum",
        "SHA256"
    ]


    for info in entries:

        for key in output_fields:

            if (
                key in info
                and info[key] != ""
            ):

                lines.append(
                    f"{key}: "
                    f"{info[key]}"
                )

        lines.append("")


    packages = "\n".join(
        lines
    )


    (
        ROOT / "Packages"
    ).write_text(
        packages,
        encoding="utf-8"
    )


    data = packages.encode(
        "utf-8"
    )


    (
        ROOT / "Packages.gz"
    ).write_bytes(
        gzip.compress(
            data,
            compresslevel=9
        )
    )


    (
        ROOT / "Packages.bz2"
    ).write_bytes(
        bz2.compress(
            data,
            compresslevel=9
        )
    )


    # ========================================================
    # 自动生成 sileo.json
    # ========================================================

    sileo = {

        "name":
            SOURCE_NAME,

        "identifier":
            SOURCE_IDENTIFIER,

        "url":
            REPO_URL,

        "version":
            "1.0",

        "contact":
            SOURCE_CONTACT,

        "packages":
            sileo_packages
    }


    (
        ROOT / "sileo.json"
    ).write_text(

        json.dumps(
            sileo,
            ensure_ascii=False,
            indent=2
        ) + "\n",

        encoding="utf-8"
    )


    # ========================================================
    # 完成
    # ========================================================

    print(
        f"\n🎉 完成："
        f"{len(entries)} 个软件包"
    )

    print(
        "📦 Packages 已生成"
    )

    print(
        "📦 Packages.gz 已生成"
    )

    print(
        "📦 Packages.bz2 已生成"
    )

    print(
        "📱 sileo.json 已自动更新"
    )

    print(
        "🎨 图标系统已处理"
    )


if __name__ == "__main__":

    main()
