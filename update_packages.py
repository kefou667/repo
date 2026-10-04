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

REPO_URL = "https://repo.xxtt.pp.ua/"

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
            class="hero-icon"
            src="{h(icon_url)}"
            alt="{h(name)}"
        >
        """

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>{h(name)} - kefou</title>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    padding: 24px 16px 50px;

    background:
        linear-gradient(
            180deg,
            #f7f7fb 0%,
            #f2f2f7 100%
        );

    color: #1c1c1e;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "SF Pro Display",
        "SF Pro Text",
        "Helvetica Neue",
        sans-serif;
}}

.container {{
    max-width: 700px;
    margin: 0 auto;
}}

.card {{
    background: rgba(255,255,255,.94);

    border-radius: 28px;

    padding: 28px;

    box-shadow:
        0 12px 40px rgba(0,0,0,.08);

    border: 1px solid rgba(0,0,0,.04);
}}

.hero {{
    text-align: center;

    padding: 10px 0 8px;
}}

.hero-icon {{
    width: 104px;
    height: 104px;

    border-radius: 24px;

    object-fit: cover;

    display: block;

    margin: 0 auto 18px;

    box-shadow:
        0 10px 28px rgba(0,0,0,.14);
}}

h1 {{
    margin: 0;

    font-size: 30px;

    line-height: 1.2;

    font-weight: 750;

    letter-spacing: -.5px;
}}

.version {{
    margin-top: 8px;

    color: #777985;

    font-size: 14px;
}}

.badges {{
    display: flex;

    justify-content: center;

    flex-wrap: wrap;

    gap: 8px;

    margin-top: 16px;
}}

.badge {{
    display: inline-flex;

    align-items: center;

    padding: 7px 12px;

    border-radius: 999px;

    background: #f0edff;

    color: #6848d8;

    font-size: 13px;

    font-weight: 650;
}}

.description {{
    margin-top: 28px;

    padding: 20px;

    background: #f7f7fa;

    border-radius: 18px;

    color: #44444a;

    font-size: 15px;

    line-height: 1.7;
}}

.section-title {{
    margin: 28px 0 14px;

    font-size: 17px;

    font-weight: 700;
}}

.info {{
    overflow: hidden;

    border-radius: 18px;

    background: #f7f7fa;
}}

.row {{
    display: grid;

    grid-template-columns: 90px 1fr;

    gap: 14px;

    padding: 14px 16px;

    border-bottom:
        1px solid rgba(0,0,0,.06);

    font-size: 14px;
}}

.row:last-child {{
    border-bottom: 0;
}}

.label {{
    color: #88888f;
}}

.value {{
    color: #222226;

    word-break: break-word;
}}

.links {{
    display: flex;

    flex-wrap: wrap;

    gap: 10px;

    margin-top: 26px;
}}

.button {{
    flex: 1;

    min-width: 130px;

    display: inline-flex;

    justify-content: center;

    align-items: center;

    padding: 13px 16px;

    border-radius: 14px;

    text-decoration: none;

    font-size: 14px;

    font-weight: 650;
}}

.button.primary {{
    background: #6d4aff;

    color: white;
}}

.button.secondary {{
    background: #f1f1f5;

    color: #333338;
}}

.footer {{
    margin-top: 24px;

    text-align: center;

    color: #9999a1;

    font-size: 12px;

    line-height: 1.6;
}}

.footer a {{
    color: #6d4aff;

    text-decoration: none;
}}

@media (max-width: 520px) {{

    body {{
        padding:
            12px 10px 35px;
    }}

    .card {{
        padding:
            22px 18px;

        border-radius: 24px;
    }}

    .hero-icon {{
        width: 92px;
        height: 92px;

        border-radius: 22px;
    }}

    h1 {{
        font-size: 27px;
    }}

    .row {{
        grid-template-columns:
            75px 1fr;
    }}

}}

</style>

</head>

<body>

<div class="container">

    <div class="card">

        <div class="hero">

            {icon_html}

            <h1>
                {h(name)}
            </h1>

            <div class="version">
                v{h(version)}
            </div>

            <div class="badges">

                <span class="badge">
                    Rootless
                </span>

                <span class="badge">
                    {h(section)}
                </span>

            </div>

        </div>


        <div class="description">

            {h(desc).replace(chr(10), "<br>")}

        </div>


        <div class="section-title">
            软件信息
        </div>


        <div class="info">

            <div class="row">

                <div class="label">
                    版本
                </div>

                <div class="value">
                    {h(version)}
                </div>

            </div>


            <div class="row">

                <div class="label">
                    架构
                </div>

                <div class="value">
                    {h(arch)}
                </div>

            </div>


            <div class="row">

                <div class="label">
                    作者
                </div>

                <div class="value">
                    {h(author)}
                </div>

            </div>


            <div class="row">

                <div class="label">
                    分类
                </div>

                <div class="value">
                    {h(section)}
                </div>

            </div>

        </div>


        <div class="links">

            <a
                class="button primary"
                href="{h(REPO_URL)}/"
            >
                返回 kefou 源
            </a>


            <a
                class="button secondary"
                href="https://kekezw.nyc.mn/"
                target="_blank"
                rel="noopener noreferrer"
            >
                📝 我的博客
            </a>


            <a
                class="button secondary"
                href="{h(SOURCE_CONTACT)}"
                target="_blank"
                rel="noopener noreferrer"
            >
                GitHub
            </a>

        </div>

    </div>


    <div class="footer">

        <div>
            {h(name)} · kefou
        </div>

        <div>

            Powered by

            <a href="{h(REPO_URL)}/">
                kefou Repository
            </a>

        </div>

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
