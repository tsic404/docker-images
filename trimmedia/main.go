// 飞牛影视（trim.media）独立镜像的**运行期**程序：单个静态 Go 二进制，
// 镜像里不再有 Python / shell 脚本 / sqlite3 CLI。
//
// 子命令：
//
//	run        入口：拉起 mediasrv、内建 rpcbroker 桩、启动影视，并做首次初始化
//	broker     单独跑 rpcbroker 桩（调试用）
//	mkpasswd   生成与 trim-media 一致的 argon2id PHC 串（seed 脚本调用）
//
// 构建期用的取包/取系统文件脚本在 build/ 下（Python，不进最终镜像）。
package main

import (
	"fmt"
	"os"
)

func usage() {
	fmt.Fprint(os.Stderr, `用法：trimmedia <子命令> [选项]

  run       入口（镜像 ENTRYPOINT）
  broker    假 rpcbroker + 应用中心 auth-path 桩
  mkpasswd  生成 argon2id PHC 串
  proxy     把应用 unix socket 暴露成 TCP（并补 X-Real-IP）
  mediasrv-stub  mediasrv 桩（音乐只用 media.version）
  gateway-stub   open-gateway API-scope 桩（音乐用它要可扫描目录）

环境变量：TRIM_ROOT / TRIM_PKGMETA / MEDIA_DIRS / TRIM_SERVICE_PORT /
          ADMIN_USER / ADMIN_PASSWORD / LOG_LEVEL / GPU_ENABLE
`)
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "run":
		err = cmdRun(os.Args[2:])
	case "broker":
		err = cmdBroker(os.Args[2:])
	case "mkpasswd":
		err = cmdMkpasswd(os.Args[2:])
	case "proxy":
		err = cmdProxy(os.Args[2:])
	case "mediasrv-stub":
		err = cmdMediaSrvStub(os.Args[2:])
	case "gateway-stub":
		err = cmdGatewayStub(os.Args[2:])
	case "-h", "--help", "help":
		usage()
		return
	default:
		fmt.Fprintf(os.Stderr, "未知子命令：%s\n", os.Args[1])
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "[fatal] %v\n", err)
		os.Exit(1)
	}
}
