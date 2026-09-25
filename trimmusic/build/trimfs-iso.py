#!/usr/bin/env python3
"""构建期（amd64）：从飞牛官方安装 ISO 里流式提取系统文件，**找齐即断开连接**，不下载整个镜像。

ISO 里 TRIMFS.TGZ（约 2.9GB）是 gzip 流，无法随机读；但所需文件（mediasrv + ffmpeg +
若干 .so + gpu_device_info.json）在 tar 里集中在一处，取完就能掐断 HTTP 流。

    python3 trimfs-iso.py [-o <输出目录>] [--iso <路径|URL|auto>]

--iso 默认 auto：从 https://www.fnnas.com/download 发现当前 x86 ISO，
并换成可用的 thunder 镜像（iso. 域名有防盗链会 403）。
本地 ISO 直接 seek 读取（秒级）；URL 则 HTTP Range 流式读，取齐即断开。
"""
import fnmatch
import os
import sys
import tarfile
import urllib.request

# 需要的东西；每个组至少要命中一次才算齐
GROUPS = [
    "./usr/trim/bin/mediasrv",
    "./usr/trim/lib/libhwinfo.so*",
    "./usr/trim/lib/libigputop.so*",
    "./usr/trim/lib/libnebula.so*",
    "./usr/trim/lib/libppjson.so*",
    "./usr/trim/config/gpu_device_info.json",
    "./usr/trim/lib/mediasrv/*",
]
# lib/mediasrv 是个目录，成员很多且连续；它之外的成员出现即说明该目录已取完
DIR_PREFIX = "./usr/trim/lib/mediasrv/"


def is_url(src):
    return src.startswith("http://") or src.startswith("https://")


def resolve_latest_iso(edition="Mainland-PE", page="https://www.fnnas.com/download"):
    """从官网下载页里取出当前 x86 ISO 地址。

    页面上给的是 https://iso.liveupdate.fnnas.com/...（有防盗链，直连 403），
    换成同一路径的官方镜像 thunder.liveupdate.fnnas.com:8080 即可正常 Range 下载。
    """
    import re
    req = urllib.request.Request(page, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    urls = re.findall(r"https://iso\.liveupdate\.fnnas\.com/[^\"\'<> ]+\.iso", html)
    if not urls:
        sys.exit("下载页里没找到 ISO 地址：%s" % page)
    pick = next((u for u in urls if edition in u), urls[0])
    return pick.replace("https://iso.liveupdate.fnnas.com/",
                        "http://thunder.liveupdate.fnnas.com:8080/")


def locate(src, name="TRIMFS.TGZ"):
    """只读 ISO9660 目录区，定位 TRIMFS.TGZ 的字节偏移与长度。"""
    import struct

    def fetch(off, length):
        if is_url(src):
            req = urllib.request.Request(src, headers={
                "Range": "bytes=%d-%d" % (off, off + length - 1), "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        with open(src, "rb") as f:
            f.seek(off)
            return f.read(length)

    def extent_len(rec):
        return struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]

    def walk(ext, ln, depth=0):
        data = fetch(ext * 2048, ln)
        i = 0
        while i < len(data):
            rl = data[i]
            if rl == 0:
                i = (i // 2048 + 1) * 2048
                continue
            rec = data[i:i + rl]
            nm = rec[33:33 + rec[32]].decode("latin1").split(";")[0]
            if nm not in ("\x00", "\x01"):
                e, l = extent_len(rec)
                if nm.upper() == name.upper():
                    return e * 2048, l
                if (rec[25] & 2) and depth < 3:
                    got = walk(e, l, depth + 1)
                    if got:
                        return got
            i += rl
        return None

    pvd = fetch(0x8000, 2048)
    if pvd[1:6] != b"CD001":
        sys.exit("不是 ISO9660 镜像：%s" % src)
    re_, rl_ = extent_len(pvd[156:156 + 34])
    got = walk(re_, rl_)
    if not got:
        sys.exit("ISO 里找不到 %s" % name)
    return got


class _Counting:
    """统计实际从 ISO 里读了多少字节 —— URL 模式下这个数就是下载量。"""

    def __init__(self, f):
        self.f = f
        self.n = 0

    def read(self, *a):
        b = self.f.read(*a)
        self.n += len(b)
        return b

    def __getattr__(self, k):
        return getattr(self.f, k)


def extract_tgz(fileobj, outdir):
    """从 TRIMFS.TGZ 流里取所需成员；取齐后立刻停止读取（调用方可据此断开连接）。"""
    done = set()
    taken = 0
    os.makedirs(outdir, exist_ok=True)
    cnt = _Counting(fileobj)
    tf = tarfile.open(fileobj=cnt, mode="r|gz")
    try:
        for m in tf:
            hit = [g for g in GROUPS if fnmatch.fnmatch(m.name, g)]
            if hit:
                tf.extract(m, path=outdir, set_attrs=True, filter="tar")  # 必须恢复权限位（mediasrv/ffmpeg 要可执行）
                taken += 1
                done.update(hit)
                continue
            # 已经离开 lib/mediasrv 目录，且所有组都命中过 -> 可以停了
            if len(done) == len(GROUPS) and not m.name.startswith(DIR_PREFIX):
                break
    finally:
        tf.close()
    print("[iso] 提取 %d 个成员，命中组 %d/%d，只读取了 %.1f MB（URL 模式下即下载量）"
          % (taken, len(done), len(GROUPS), cnt.n / 1048576.0), flush=True)
    if len(done) != len(GROUPS):
        sys.exit("缺组：%s" % sorted(set(GROUPS) - done))
    return taken


def fixup_sonames(outdir):
    """ISO 的 tgz 把 soname 存成 0 字节占位，这里按最新版本号补相对软链。"""
    lib = os.path.join(outdir, "usr/trim/lib")
    if not os.path.isdir(lib):
        return
    import glob
    for f in glob.glob(os.path.join(lib, "*.so*")):
        if os.path.isfile(f) and os.path.getsize(f) == 0:
            cands = sorted(glob.glob(f + ".*"))
            if cands:
                os.remove(f)
                os.symlink(os.path.basename(cands[-1]), f)
                print("[iso] 重建软链 %s -> %s" % (os.path.basename(f), os.path.basename(cands[-1])))


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--iso", default="auto", help="ISO 路径 / URL / auto")
    p.add_argument("-o", "--out", required=True, help="输出目录（得到 usr/trim/...）")
    opts = p.parse_args()
    src, outdir = opts.iso, opts.out
    if src in ("auto", "latest", ""):
        src = resolve_latest_iso()
        print("[iso] 自动发现最新 ISO：%s" % src, flush=True)
    off, size = locate(src)
    print("[iso] TRIMFS.TGZ @ %d (%d 字节) <- %s" % (off, size, src), flush=True)

    if is_url(src):
        req = urllib.request.Request(src, headers={
            "Range": "bytes=%d-%d" % (off, off + size - 1), "User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=180)
    else:
        resp = open(src, "rb")
        resp.seek(off)
    try:
        extract_tgz(resp, outdir)
    finally:
        resp.close()
    fixup_sonames(outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
