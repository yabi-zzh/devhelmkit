#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chromedriver 自动下载脚本。

根据设备 WebView 内核版本号，从 Chrome for Testing 官方源下载对应版本
chromedriver 二进制到本地目录，免去手动下载和版本匹配的麻烦。

用法:
    # 下载指定版本到默认目录 ./chromedriver/
    python scripts/download_chromedriver.py 114

    # 下载到指定目录
    python scripts/download_chromedriver.py 114 -o /path/to/chromedriver_search_path

    # 自动探测设备 WebView 版本并下载
    python scripts/download_chromedriver.py --auto

    # 自动探测 + 指定设备序列号
    python scripts/download_chromedriver.py --auto --serial <device-serial>

    # 列出可用版本
    python scripts/download_chromedriver.py --list

下载后的目录结构:
    chromedriver_search_path/
    ├── chromedriver_114/
    │   ├── chromedriver.exe      # Windows
    │   ├── chromedriver          # Linux
    │   └── chromedriver.mac      # macOS
    └── chromedriver_132/
        ├── chromedriver.exe
        ├── chromedriver
        └── chromedriver.mac

该目录可直接传给 d.webview() 的 chromedriver_search_path 参数。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import stat
import sys
import tempfile
import urllib.request
import zipfile
from typing import Optional

# Chrome for Testing 官方 API
CFT_VERSIONS_URL = "https://googlechromelabs.github.io/chrome-for-testing/latest-versions-per-milestone-with-downloads.json"
CFT_LATEST_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"

# 默认输出目录
DEFAULT_OUTPUT_DIR = "chromedriver"

# 平台标识映射
PLATFORM_MAP = {
    "Windows": "win64",
    "Linux": "linux64",
    "Darwin": "mac-x64",
}


def get_platform_id() -> str:
    """获取当前平台的 Chrome for Testing 标识。"""
    system = platform.system()
    pid = PLATFORM_MAP.get(system)
    if pid is None:
        print("不支持的平台: %s" % system)
        sys.exit(1)
    return pid


def get_binary_name() -> str:
    """获取当前平台的 chromedriver 二进制文件名。"""
    system = platform.system()
    if system == "Windows":
        return "chromedriver.exe"
    if system == "Darwin":
        return "chromedriver.mac"
    return "chromedriver"


def fetch_json(url: str) -> dict:
    """下载 JSON 并解析。"""
    print("获取版本信息: %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": "devhelmkit"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_closest_version(target_major: int, versions_data: dict) -> dict:
    """在按主版本号组织的版本数据中查找目标版本。

    latest-versions-per-milestone-with-downloads.json 的结构为:
        {"milestones": {"114": {"version": "114.0.5735.133", "downloads": {...}}, ...}}

    Returns:
        包含 version 字符串和 downloads 字典的版本条目
    """
    milestones = versions_data.get("milestones", {})
    if str(target_major) in milestones:
        return milestones[str(target_major)]

    # 找不到精确匹配，找最接近的更小版本
    available = []
    for key, entry in milestones.items():
        try:
            major = int(key)
        except ValueError:
            continue
        if major <= target_major:
            available.append((major, entry))

    if available:
        available.sort(key=lambda x: x[0], reverse=True)
        return available[0][1]

    print("未找到主版本号 <= %d 的 chromedriver 版本" % target_major)
    sys.exit(1)


def _build_legacy_url(major: int) -> Optional[str]:
    """构造旧版 chromedriver 下载 URL（适用于 < 115 版本）。

    旧版下载源通过 LATEST_RELEASE_{major} 获取精确版本号：
        https://chromedriver.storage.googleapis.com/LATEST_RELEASE_114 -> 114.0.5735.90
    然后拼接下载 URL:
        https://chromedriver.storage.googleapis.com/{version}/chromedriver_{platform}.zip
    """
    # 查询该主版本号对应的精确版本
    latest_url = "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_%d" % major
    req = urllib.request.Request(latest_url, headers={"User-Agent": "devhelmkit"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            version_str = resp.read().decode("utf-8").strip()
    except Exception as e:
        print("查询旧版 chromedriver 版本失败: %s" % e)
        return None

    system = platform.system()
    if system == "Windows":
        legacy_platform = "win32"
    elif system == "Darwin":
        legacy_platform = "mac64"
    else:
        legacy_platform = "linux64"
    return "https://chromedriver.storage.googleapis.com/%s/chromedriver_%s.zip" % (
        version_str, legacy_platform
    )


def download_and_extract(version_entry: dict, output_dir: str) -> str:
    """下载并解压 chromedriver。

    优先使用 Chrome for Testing API 的 chromedriver 下载链接（>= 115），
    回退到旧版 chromedriver.storage.googleapis.com（< 115）。

    Returns:
        chromedriver 二进制最终路径
    """
    version_str = version_entry["version"]
    major = int(version_str.split(".")[0])
    target_dir = os.path.join(output_dir, "chromedriver_%d" % major)
    os.makedirs(target_dir, exist_ok=True)

    binary_name = get_binary_name()
    final_path = os.path.join(target_dir, binary_name)

    # 已存在则跳过
    if os.path.isfile(final_path):
        print("已存在，跳过: %s" % final_path)
        return final_path

    # 优先：Chrome for Testing API 的 chromedriver 下载链接
    pid = get_platform_id()
    downloads = version_entry.get("downloads", {}).get("chromedriver", [])
    download_url = None
    for item in downloads:
        if item.get("platform") == pid:
            download_url = item.get("url")
            break

    # 回退：旧版 chromedriver.storage.googleapis.com（< 115）
    if download_url is None:
        download_url = _build_legacy_url(major)
        if download_url is None:
            print("版本 %s 无 %s 平台下载链接" % (version_str, pid))
            sys.exit(1)
        print("Chrome for Testing 无 chromedriver 下载，回退到旧版源")

    # 下载 zip；失败或中断时删除半截文件，避免残留损坏包干扰下次下载
    print("下载: %s" % download_url)
    tmp_zip = os.path.join(tempfile.gettempdir(), "chromedriver_%s.zip" % version_str)
    req = urllib.request.Request(download_url, headers={"User-Agent": "devhelmkit"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(tmp_zip, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    except BaseException:
        if os.path.isfile(tmp_zip):
            os.remove(tmp_zip)
        raise

    try:
        # 解压前校验 zip 完整性，损坏包直接报错而非产出坏二进制
        print("解压到: %s" % target_dir)
        with zipfile.ZipFile(tmp_zip) as zf:
            bad_entry = zf.testzip()
            if bad_entry is not None:
                print("zip 包损坏（条目 %s 校验失败），请重试下载" % bad_entry)
                sys.exit(1)

            # zip 内二进制条目名固定为 chromedriver / chromedriver.exe
            # （可能位于子目录），只取 basename 精确相等的第一个，
            # 避免 LICENSE.chromedriver 之类条目覆盖目标文件
            entry_name = (
                "chromedriver.exe" if platform.system() == "Windows"
                else "chromedriver"
            )
            entry = None
            for info in zf.infolist():
                if os.path.basename(info.filename) == entry_name:
                    entry = info
                    break
            if entry is None:
                print("zip 包中未找到 %s 条目" % entry_name)
                sys.exit(1)

            with zf.open(entry) as src:
                with open(final_path, "wb") as dst:
                    dst.write(src.read())
    finally:
        os.remove(tmp_zip)

    # 设置可执行权限（非 Windows）
    if platform.system() != "Windows":
        os.chmod(final_path, stat.S_IRWXU)

    print("完成: %s" % final_path)
    return final_path


def list_versions() -> None:
    """列出最近的可用版本。"""
    data = fetch_json(CFT_LATEST_URL)
    for channel in ("Stable", "Beta", "Dev", "Canary"):
        info = data.get("channels", {}).get(channel)
        if not info:
            continue
        version = info.get("version", "?")
        print("  %-8s %s" % (channel, version))


def detect_webview_version(serial: str | None) -> int:
    """通过 hdc 探测设备 WebView 内核版本。

    Args:
        serial: 设备序列号，None 时自动发现

    Returns:
        WebView 主版本号
    """
    try:
        from devhelmkit.harmony.device.hdc import HdcDevice
    except ImportError:
        print("无法导入 devhelmkit，请确认已安装或处于项目根目录")
        sys.exit(1)

    if serial is None:
        targets = HdcDevice.list_targets()
        if not targets:
            print("未检测到设备")
            sys.exit(1)
        serial = targets[0]
        print("自动选择设备: %s" % serial)

    device = HdcDevice(serial)

    # 方法一：通过 hdc shell 读取 webview 版本
    output = device.shell(
        "cat /system/etc/webview/version.json 2>/dev/null"
    )
    import re
    match = re.search(r'"version"\s*:\s*"(\d+)\.', output)
    if match:
        version = int(match.group(1))
        print("设备 WebView 版本: %d" % version)
        return version

    # 方法二：通过 hidumper 查询
    output = device.shell("hidumper -s WebViewService -a -h 2>/dev/null | head -20")
    match = re.search(r'(\d+)\.\d+\.\d+', output)
    if match:
        version = int(match.group(1))
        print("设备 WebView 版本: %d" % version)
        return version

    print("无法自动探测 WebView 版本，请手动指定版本号")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="chromedriver 自动下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "version",
        nargs="?",
        type=int,
        help="chromedriver 主版本号（如 114）",
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录（默认 ./chromedriver/）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="自动探测设备 WebView 版本",
    )
    parser.add_argument(
        "--serial",
        default=None,
        help="设备序列号（--auto 模式下使用）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出最近的可用版本",
    )
    args = parser.parse_args()

    if args.list:
        list_versions()
        return

    if args.auto:
        target_version = detect_webview_version(args.serial)
    elif args.version is not None:
        target_version = args.version
    else:
        parser.print_help()
        sys.exit(1)

    print("目标 chromedriver 版本: %d" % target_version)
    versions_data = fetch_json(CFT_VERSIONS_URL)
    version_entry = find_closest_version(target_version, versions_data)
    print("匹配版本: %s" % version_entry["version"])
    download_and_extract(version_entry, args.output)

    print()
    print("下载完成。使用方式:")
    print('  d.webview("com.xxx", chromedriver_search_path="%s")' % os.path.abspath(args.output))


if __name__ == "__main__":
    main()