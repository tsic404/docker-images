// 飞牛音乐（trim.music）独立镜像的运行期程序：单个静态 Go 二进制。
//
// 子命令：
//
//	run          入口：拉起 mediasrv、内建 rpcbroker / open-gateway 桩、反代音乐 UI，并做首次初始化
//	broker       假 rpcbroker + 应用中心 auth-path 桩
//	gateway-stub open-gateway 的 API-scope 桩（音乐用它要可扫描目录）
//	proxy        把音乐 app 的 unix socket 暴露成 TCP（补 X-Real-IP）
//	mkpasswd     生成 bcrypt(sha256hex(明文)) 口令串（seed 脚本调用）
//
// 构建期取包/取系统文件脚本在 build/ 下（Python，不进最终镜像）。
package main

import (
	"fmt"
	"os"
)

func usage() {
	fmt.Fprint(os.Stderr, `用法：trimmusic <子命令> [选项]

  run           入口（镜像 ENTRYPOINT）
  broker        假 rpcbroker + 应用中心 auth-path 桩
  gateway-stub  open-gateway API-scope 桩（返回可扫描目录）
  proxy         音乐 unix socket -> TCP（补 X-Real-IP）
  mkpasswd      生成 bcrypt(sha256hex(明文))

环境变量：TRIM_PKGVAR / TRIM_APPDEST / TRIM_SYS_MACHINE_ID / TRIM_API_TOKEN /
          MEDIA_DIRS / TRIM_PROXY_ADDR / ADMIN_USER / ADMIN_PASSWORD / LOG_LEVEL
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
	case "gateway-stub":
		err = cmdGatewayStub(os.Args[2:])
	case "proxy":
		err = cmdProxy(os.Args[2:])
	case "mkpasswd":
		err = cmdMkpasswd(os.Args[2:])
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
