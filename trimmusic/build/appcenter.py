#!/usr/bin/env python3
"""构建期：从飞牛应用中心取「指定/最新」版本的影视本体并解密解包。

云端接口（请求头即鉴权）：
    POST https://aps.fnnas.com/api/v1/app/list   {}                         -> 应用清单
    POST https://aps.fnnas.com/api/v1/app/apply  {"appId":N,"version":"x"}  -> 下载信息
    headers: trim-machine-id / trim-os-version / trim-platform / trim-timestamp

.tpk 不是普通压缩包，而是 AES-256-CFB 加密的 tar：
    key = sha256("`".join([appName, version, encryptBlock, "trimAppCenter"]))
    iv  = key[:16]
    plaintext = AES-256-CFB(key, iv).decrypt(tpk) -> POSIX tar
（发布时未写 tar 结尾的 0 块，末尾会 Unexpected EOF，属正常）

输出布局：
    <out>/payload/   应用本体（app.tgz 解开后的 trim-media、static、ui、json）
    <out>/pkg/       tpk 里的元数据（manifest / config / cmd / wizard / ICON）

用法：appcenter.py --version 0.9.8-1 --arch amd64 -o /out
"""
import argparse
import hashlib
import json
import os
import sys
import tarfile
import urllib.request

API = "https://aps.fnnas.com/api/v1"
SUFFIX = "trimAppCenter"  # GetEncryptKey 内部固定追加的常量
SEP = "`"                 # GetEncryptKey 的 join 分隔符
DEFAULT_OS_VERSION = os.environ.get("TRIM_OS_VERSION", "1.2.0701")
DEFAULT_MACHINE_ID = os.environ.get("TRIM_MACHINE_ID", "0" * 40)


def platform_of(arch):
    return {"amd64": "x86", "x86_64": "x86", "x86": "x86",
            "arm64": "arm", "aarch64": "arm", "arm": "arm"}.get(arch)


def cloud_post(path, body, platform, timeout=60):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "trim-machine-id": DEFAULT_MACHINE_ID,
            "trim-os-version": DEFAULT_OS_VERSION,
            "trim-platform": platform,
            "trim-timestamp": str(int(__import__("time").time() * 1000)),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("code") != 0:
        raise SystemExit("云端接口 %s 失败：code=%s msg=%s" % (path, payload.get("code"), payload.get("msg")))
    return payload.get("data")


def resolve(app_name, version, platform, app_id=None):
    data = cloud_post("/app/list", {}, platform)
    items = (data or {}).get("list") or []
    app = None
    if app_id is not None:
        app = next((i for i in items if i.get("appId") == app_id), None)
    if app is None:
        app = next((i for i in items if i.get("appName") == app_name), None)
    if app is None:
        raise SystemExit("应用中心里找不到 %s" % app_name)
    ver = app.get("lastVersion") if version in ("", "auto", None) else version
    dl = cloud_post("/app/apply", {"appId": app["appId"], "version": ver}, platform)
    if not dl.get("downloadLink") or not dl.get("encryptBlock"):
        raise SystemExit("云端未返回下载链接或加密块：%r" % (dl,))
    return app, ver, dl


def decrypt(reader, app_name, version, encrypt_block, writer):
    """AES-256-CFB 流式解密：读 reader 写 writer，同时累计 MD5。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from cryptography.hazmat.decrepit.ciphers.modes import CFB

    key = hashlib.sha256(SEP.join([app_name, version, encrypt_block, SUFFIX]).encode()).digest()
    dec = Cipher(algorithms.AES(key), CFB(key[:16])).decryptor()
    md5 = hashlib.md5()
    while True:
        chunk = reader.read(1 << 20)
        if not chunk:
            break
        md5.update(chunk)
        out = dec.update(chunk)
        if out:
            writer.write(out)
    tail = dec.finalize()
    if tail:
        writer.write(tail)
    return md5.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app-name", default="trim.media")
    p.add_argument("--app-id", type=int, default=None, help="应用中心 appId（影视=2、音乐=333）")
    p.add_argument("--bin", default="trim-media", help="应用本体可执行文件名")
    p.add_argument("--version", default="auto", help="应用版本，auto=云端最新")
    p.add_argument("--arch", default="amd64", help="目标架构 amd64/arm64（决定向云端要哪个构建）")
    p.add_argument("-o", "--out", required=True)
    opts = p.parse_args()

    platform = platform_of(opts.arch)
    if not platform:
        raise SystemExit("不支持的架构：%s" % opts.arch)

    app, ver, dl = resolve(opts.app_name, opts.version, platform, opts.app_id)
    print("应用   : %s (%s)" % (app.get("displayName"), app.get("appName")))
    print("版本   : %s (versionId=%s)" % (ver, app.get("lastVersionId")))
    print("平台   : %s" % platform)
    print("下载   : %s" % dl["downloadLink"])
    print("大小   : %s bytes" % dl.get("fileSize"))

    payload_dir = os.path.join(opts.out, "payload")
    pkg_dir = os.path.join(opts.out, "pkg")
    os.makedirs(payload_dir, exist_ok=True)
    os.makedirs(pkg_dir, exist_ok=True)

    # 边下边解密，落到临时 tar
    import tempfile
    with urllib.request.urlopen(dl["downloadLink"], timeout=1800) as resp, \
            tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tf:
        tar_path = tf.name
        got = decrypt(resp, app["appName"], ver, dl["encryptBlock"], tf)
    print("MD5    : %s" % got)
    if dl.get("checkSum") and got != dl["checkSum"]:
        raise SystemExit("tpk 校验失败：期望 %s" % dl["checkSum"])

    # 解 tar：app.tgz 落 payload/，其余元数据落 pkg/
    # 注意：飞牛发布时未写 tar 结尾的 0 块，遍历到末尾会 ReadError("unexpected end of data")，属正常
    def iter_tar(tf):
        try:
            for member in tf:
                yield member
        except (tarfile.ReadError, EOFError):
            return

    with tarfile.open(tar_path, "r:") as tar:
        for m in iter_tar(tar):
            name = m.name.lstrip("./")
            if not name:
                continue
            if name == "app.tgz":
                f = tar.extractfile(m)
                with tarfile.open(fileobj=f, mode="r:gz") as inner:
                    for im in iter_tar(inner):
                        inner.extract(im, path=payload_dir, set_attrs=True, filter="tar")
                continue
            if m.isfile():
                m.name = name
                tar.extract(m, path=pkg_dir, set_attrs=True, filter="tar")
    os.remove(tar_path)

    bin_path = os.path.join(payload_dir, opts.bin)
    if not os.path.isfile(bin_path):
        raise SystemExit("解包结果里没有 %s：%s" % (opts.bin, bin_path))
    os.chmod(bin_path, 0o755)
    print("已解包 : %s + %s" % (payload_dir, pkg_dir))


if __name__ == "__main__":
    sys.exit(main())
