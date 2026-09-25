#!/usr/bin/env python3
"""隐藏影视登录页的「使用 NAS 登录」按钮。

独立部署没有 NAS 可登，按钮留着只会点出「服务异常」。

**为什么是隐藏而不是删除**：实测把该按钮元素整体替换成 `null` 会让整个登录页
渲染成「网络异常，请检查后重试」（React 的 globalError 兜底），而语法检查、
接口返回、控制台都无异常 —— 删除元素这个语义改动本身破坏了页面。
改为**保留元素、加 style 隐藏**后页面完全正常（对照实验：原版只加一个空格也正常）。

定位方式：锚定该按钮独有的属性序列 `,theme:`solid`,type:`tertiary`,size:`large`,disabled:`
（登录按钮是 type:`primary`、htmlType:`submit`，不会误伤），插入 `style:{display:`none`},`。
不依赖压缩后的变量名，应用升级后仍可用；末尾断言唯一命中且 i18n 键仍在。

用法：patch-ui.py <assets 目录> [更多目录...]
"""
import glob
import os
import sys

ANCHOR = ",theme:`solid`,type:`tertiary`,size:`large`,disabled:"
PATCHED = ",theme:`solid`,type:`tertiary`,size:`large`,style:{display:`none`},disabled:"
KEY = "auth.login.loginWithNas"


def patch_file(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        s = f.read()
    if KEY not in s:
        return 0
    n = s.count(ANCHOR)
    if n != 1:
        raise SystemExit(f"{path}: 命中 {n} 处按钮锚点（期望 1），补丁需重新定位")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s.replace(ANCHOR, PATCHED))
    return 1


def main() -> int:
    roots = sys.argv[1:] or ["/app/payload/static/assets"]
    total = 0
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "*.js"))):
            total += patch_file(f)
    if total == 0:
        raise SystemExit("未找到「使用 NAS 登录」按钮，应用结构可能已变化，补丁需重新定位")
    # 断言：i18n 键仍在（元素保留），且隐藏样式已注入
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "*.js"))):
            with open(f, encoding="utf-8") as fh:
                c = fh.read()
            if KEY in c and "display:`none`" not in c:
                raise SystemExit(f"{f}: 按钮未成功隐藏")
    print(f"已隐藏登录页的 NAS 登录按钮（{total} 处）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
