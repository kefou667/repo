#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
kefou源 Packages 生成器
- 无需 dpkg-deb
- 支持 control.tar.gz / control.tar.xz / control.tar
- 生成 Packages / Packages.gz / Packages.bz2
- 自动生成基础 HTML/JSON Depiction
"""

import bz2
import gzip
import hashlib
import html
import lzma
import tarfile
from pathlib import Path

REPO_URL = "https://kefou.github.io/Sileo"

ROOT = Path(__file__).resolve().parent
DEBS = ROOT / "debs"
DEPICTIONS = ROOT / "depictions"

FIELDS = [
    "Package", "Name", "Version", "Architecture", "Description",
    "Maintainer", "Author", "Section", "Depends", "Pre-Depends",
    "Recommends", "Conflicts", "Provides", "Replaces", "Icon",
    "Filename", "Size"
]

def read_control_from_deb(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw.startswith(b"!<arch>\n"):
        raise ValueError("不是标准 .deb/ar 文件")

    pos = 8
    while pos + 60 <= len(raw):
        hdr = raw[pos:pos + 60]
        if hdr[58:60] != b"`\n":
            break

        name = hdr[0:16].rstrip(b" /").decode("ascii", "replace").strip()
        try:
            size = int(hdr[48:58].strip())
        except ValueError:
            break

        data_start = pos + 60
        member = raw[data_start:data_start + size]
        pos = data_start + size + (size & 1)

        if name not in ("control.tar.gz", "control.tar.xz", "control.tar"):
            continue

        if name.endswith(".gz"):
            tar_data = gzip.decompress(member)
        elif name.endswith(".xz"):
            tar_data = lzma.decompress(member)
        else:
            tar_data = member

        with tarfile.open(fileobj=__import__("io").BytesIO(tar_data), mode="r:") as tar:
            try:
                f = tar.extractfile("./control")
            except KeyError:
                try:
                    f = tar.extractfile("control")
                except KeyError:
                    f = None

            if f is None:
                # 兼容不同打包工具的 control 路径
                for m in tar.getmembers():
                    if m.name.rstrip("/").endswith("/control") or m.name == "control":
                        f = tar.extractfile(m)
                        break

            if f is None:
                raise ValueError("control.tar 中找不到 control")

            text = f.read().decode("utf-8", "replace")

        info = {}
        current_key = None
        for line in text.splitlines():
            if line.startswith((" ", "\t")) and current_key:
                info[current_key] += "\n" + line.strip()
                continue
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            current_key = k
            if k in FIELDS:
                info[k] = v

        return info

    raise ValueError("找不到 control.tar.*")

def digest(path, algorithm):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def write_depictions(info):
    package = info.get("Package", "unknown")
    safe = package.replace("/", "_")
    name = info.get("Name", package)
    version = info.get("Version", "")
    arch = info.get("Architecture", "")
    desc = info.get("Description", "暂无描述")
    author = info.get("Author") or info.get("Maintainer", "未知")
    section = info.get("Section", "Tweaks")

    # JSON depiction
    depiction_json = {
        "class": "DepictionTabView",
        "minVersion": "0.3",
        "tabs": [
            {
                "class": "DepictionStackView",
                "tabname": "描述",
                "views": [
                    {"class": "DepictionMarkdownView",
                     "markdown": f"## {name}\n{desc}",
                     "useSpacing": True},
                    {"class": "DepictionSeparatorView"},
                    {"class": "DepictionHeaderView",
                     "title": "信息",
                     "useBoldText": True},
                    {"class": "DepictionTableTextView", "title": "作者", "text": author},
                    {"class": "DepictionTableTextView", "title": "版本", "text": version},
                    {"class": "DepictionTableTextView", "title": "架构", "text": arch},
                    {"class": "DepictionTableTextView", "title": "分类", "text": section}
                ]
            }
        ]
    }
    (DEPICTIONS / f"{safe}.json").write_text(
        __import__("json").dumps(depiction_json, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # HTML fallback depiction
    h = html.escape
    html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{h(name)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:24px;background:#f2f2f7;color:#1c1c1e}}
.card{{max-width:680px;margin:auto;background:white;border-radius:18px;padding:24px;box-shadow:0 4px 20px #0001}}
h1{{margin-top:0}} .meta{{display:grid;grid-template-columns:100px 1fr;gap:8px 12px;color:#555}}
</style>
</head>
<body><div class="card">
<h1>{h(name)}</h1>
<p>{h(desc).replace(chr(10), "<br>")}</p>
<hr>
<div class="meta">
<div>版本</div><div>{h(version)}</div>
<div>架构</div><div>{h(arch)}</div>
<div>作者</div><div>{h(author)}</div>
<div>分类</div><div>{h(section)}</div>
</div>
</div></body></html>"""
    (DEPICTIONS / f"{safe}.html").write_text(html_doc, encoding="utf-8")

def main():
    DEBS.mkdir(exist_ok=True)
    DEPICTIONS.mkdir(exist_ok=True)

    entries = []

    for deb in sorted(DEBS.glob("*.deb")):
        try:
            info = read_control_from_deb(deb)
            package = info.get("Package")
            version = info.get("Version")
            arch = info.get("Architecture")

            if not package or not version or not arch:
                raise ValueError("缺少 Package / Version / Architecture")

            if arch not in ("iphoneos-arm64", "iphoneos-arm64e", "all", "any"):
                print(f"⚠️ {deb.name}: Architecture={arch}，仍保留，但请确认它是否适合 rootless")

            info["Filename"] = f"debs/{deb.name}"
            info["Size"] = str(deb.stat().st_size)

            write_depictions(info)
            stem = package.replace("/", "_")

            info["Depiction"] = f"{REPO_URL}/depictions/{stem}.html"
            info["Sileodepiction"] = f"{REPO_URL}/depictions/{stem}.json"
            info["MD5sum"] = digest(deb, "md5")
            info["SHA256"] = digest(deb, "sha256")

            entries.append(info)
            print(f"✅ {deb.name} [{package} {version} {arch}]")

        except Exception as e:
            print(f"⚠️ 跳过 {deb.name}: {e}")

    lines = []
    output_fields = [
        "Package", "Name", "Version", "Architecture", "Description",
        "Maintainer", "Author", "Depiction", "Sileodepiction",
        "Section", "Depends", "Pre-Depends", "Recommends", "Conflicts",
        "Provides", "Replaces", "Icon", "Filename", "Size", "MD5sum", "SHA256"
    ]

    for info in entries:
        for key in output_fields:
            if key in info and info[key] != "":
                lines.append(f"{key}: {info[key]}")
        lines.append("")

    packages = "\n".join(lines)
    (ROOT / "Packages").write_text(packages, encoding="utf-8")
    data = packages.encode("utf-8")

    (ROOT / "Packages.gz").write_bytes(gzip.compress(data, compresslevel=9))
    (ROOT / "Packages.bz2").write_bytes(bz2.compress(data, compresslevel=9))

    print(f"\n🎉 完成：{len(entries)} 个软件包")

if __name__ == "__main__":
    main()
