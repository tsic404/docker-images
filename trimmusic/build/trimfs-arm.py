#!/usr/bin/env python3
"""构建期（arm64）：从飞牛官方 ARM 设备镜像里取出 /usr/trim 系统文件。

飞牛没有 ARM 版 ISO —— ARM 系统是按设备发布的 `.img.gz` 磁盘镜像（GPT 分区）。
x86 走 ISO 里的 TRIMFS.TGZ（见 trimfs-iso.py），ARM 走这里。

流程：
    1. 从 https://fnnas.com/download-arm 发现当前版本与 rock-5b 镜像地址
       （页面给的是 download.liveupdate.fnnas.com，有防盗链 403，换 thunder 镜像）
    2. 流式 gunzip，解析 GPT，定位 rootfs 分区（实测是 btrfs）
    3. 只把该分区区域写成本地稀疏文件（跳过前面 370MB 的 BOOT 分区与零块）
    4. 用 btrfs restore 直接取出 /usr/trim（无需 root、无需挂载）

用法：trimfs-arm.py -o /out [--device rock-5b] [--img <路径|URL>]
"""
import argparse
import gzip
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request

ARM_PAGE = "https://www.fnnas.com/download-arm"
# download.liveupdate.fnnas.com 有防盗链（403），thunder 镜像同路径可用
MIRROR_HOST = "http://thunder.liveupdate.fnnas.com:8080/"
ORIGIN_HOST = "https://download.liveupdate.fnnas.com/"
CHUNK = 1 << 20


def http_open(url, off=None, length=None, timeout=1800):
    headers = {"User-Agent": "Mozilla/5.0"}
    if off is not None:
        headers["Range"] = "bytes=%d-%d" % (off, off + length - 1)
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def to_mirror(url):
    """官方下载域名有防盗链，换成同路径的 thunder 镜像。"""
    return url.replace(ORIGIN_HOST, MIRROR_HOST)


def discover(device):
    with http_open(ARM_PAGE) as r:
        html = r.read().decode("utf-8", "replace")
    urls = re.findall(r"https://download\.liveupdate\.fnnas\.com/arm/image/[^\"'<> ]+\.img\.gz", html)
    if not urls:
        raise SystemExit("下载页里没找到 ARM 镜像：%s" % ARM_PAGE)
    pick = next((u for u in urls if "/%s/" % device in u), None)
    if pick is None:
        names = sorted({u.split("/")[5] for u in urls if u.count("/") > 5})
        raise SystemExit("没有 %s 的镜像；可选：%s" % (device, " ".join(names)))
    return pick


def parse_gpt(reader):
    """从流里读出 GPT 分区表，返回 (name, first_lba, last_lba) 列表。"""
    reader.seek(0)
    head = reader.read(34 * 512)
    if head[510:512] != b"\x55\xaa":
        raise SystemExit("不是 MBR/GPT 镜像")
    hdr = head[512:512 + 92]
    if hdr[:8] != b"EFI PART":
        raise SystemExit("没有 GPT 头（飞牛 ARM 镜像预期为 GPT）")
    part_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    off = part_lba * 512
    reader.seek(off)
    ents = reader.read(num * esz)
    parts = []
    for i in range(num):
        e = ents[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first, last = struct.unpack_from("<QQ", e, 32)
        name = e[56:128].decode("utf-16-le").rstrip("\x00")
        parts.append((name, first, last))
    return parts


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default="rock-5b", help="ARM 设备镜像名，默认 rock-5b")
    p.add_argument("--img", help="直接指定镜像路径或 URL（跳过发现）")
    p.add_argument("-o", "--out", required=True, help="输出目录（得到 usr/trim/...）")
    p.add_argument("--keep-ext4", action="store_true", help="保留中间分区镜像文件")
    opts = p.parse_args()

    if opts.img and os.path.isfile(opts.img):
        src = opts.img
        opener = lambda: open(src, "rb")
    else:
        src = to_mirror(opts.img) if opts.img else to_mirror(discover(opts.device))
        print("[arm] 镜像：%s" % src)
        if src.startswith("http://"):
            print("[warn] 系统文件经明文 HTTP 从镜像站获取，且上游未提供校验和；"
                  "对完整性有要求时请用本地镜像（--iso / --img）", flush=True)
        opener = lambda: http_open(src)

    # 用前 32MB 解出分区表（GPT 头 + 分区项都在最前面）
    with opener() as r, gzip.GzipFile(fileobj=r) as gz:
        head = gz.read(32 << 20)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(head)
    tmp.flush()
    parts = parse_gpt(tmp)
    print("[arm] 分区：%s" % ", ".join("%s(%dMB)" % (n, (l - f + 1) * 512 // 1048576) for n, f, l in parts))
    root = next((x for x in parts if x[0] == "rootfs"), None)
    if root is None:
        raise SystemExit("镜像里没有 rootfs 分区")
    _, first, last = root
    start, size = first * 512, (last - first + 1) * 512
    print("[arm] rootfs 偏移 %d，大小 %.1f GB" % (start, size / 1073741824))

    # 流式解压，只把 rootfs 区域写成稀疏文件（跳过前面 BOOT 与全零块）
    tmp.seek(0)
    tmp.truncate(0)
    pos = 0
    written = 0
    with opener() as r, gzip.GzipFile(fileobj=r) as gz:
        while True:
            chunk = gz.read(CHUNK)
            if not chunk:
                break
            end = pos + len(chunk)
            if end > start:
                lo = max(0, start - pos)
                piece = chunk[lo:]
                if any(piece):
                    tmp.seek(written)
                    tmp.write(piece)
                    written += len(piece)
                else:
                    written += len(piece)
            pos = end
            if pos >= start + size:
                break
    tmp.truncate(written)
    tmp.flush()
    tmp.close()
    print("[arm] ext4 已落地：%.1f GB（稀疏）" % (os.path.getsize(tmp.name) / 1073741824))

    # 用 btrfs restore 直接读镜像，无需 root / 挂载；--path-regex 只取 usr/trim
    tool = None
    for cand in ("btrfs", "btrfs-progs"):
        if shutil.which(cand):
            tool = cand
            break
    if tool is None:
        raise SystemExit("缺少 btrfs（安装 btrfs-progs）")
    # btrfs restore 的 --path-regex 会连目录一起剪掉，这里全量恢复后再只留 usr/trim
    # （恢复物只落在构建阶段的临时目录里，不会进最终镜像）
    stage = tempfile.mkdtemp(prefix="trimfs-arm-")
    try:
        # -m 会恢复 owner/mode/times，但 chown 需要 root；构建阶段是 root，
        # 非 root 本地调试时退回只恢复内容，权限由后面的 chmod 兜底。
        args = [tool, "restore", "-i"]
        if os.geteuid() == 0:
            args.append("-m")
        args += [tmp.name, stage]
        subprocess.run(args, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        src_dir = os.path.join(stage, "usr", "trim")
        if not os.path.isdir(src_dir):
            raise SystemExit("btrfs restore 没能取出 /usr/trim")
        dst_dir = os.path.join(opts.out, "usr")
        os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src_dir, os.path.join(dst_dir, "trim"))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if not opts.keep_ext4:
            os.remove(tmp.name)

    # btrfs restore 写入失败（如磁盘配额不足）时只打 ERROR 但仍返回 0，
    # 结果是文件存在却为空，必须在构建期就发现，否则要到运行时自检才炸。
    # mediasrv 会自己调用 ffmpeg/ffprobe，三个都必须是可执行的
    for rel in ("bin/mediasrv", "lib/mediasrv/ffmpeg", "lib/mediasrv/ffprobe"):
        f = os.path.join(opts.out, "usr/trim", rel)
        if not os.path.isfile(f):
            raise SystemExit("结果里缺少 %s（系统文件不完整）" % rel)
        if os.path.getsize(f) == 0:
            raise SystemExit("结果里 %s 为空（多半是暂存目录磁盘空间不足，"
                             "可用 TMPDIR 指向大分区）" % rel)
        os.chmod(f, 0o755)
    print("[arm] 完成：%s" % opts.out)


if __name__ == "__main__":
    sys.exit(main())
