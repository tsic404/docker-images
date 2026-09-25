package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
)

// 飞牛音乐的「mediasrv 桩」：应用只用它做 media.version 健康检查
// （实测登录/浏览/接口全程只调这一个方法），因此不装真实 mediasrv 也能跑。
// 真实 mediasrv 是 fnOS 系统文件（要从官方 ISO 取约 490MB），桩掉它可大幅简化镜像。
const mediaSrvSock = "/var/run/mediasrv.socket"

func startMediaSrvStub(logPath string) error {
	openLog(logPath)
	os.MkdirAll(dirOf(mediaSrvSock), 0o755)
	os.Remove(mediaSrvSock)
	ln, err := net.Listen("unix", mediaSrvSock)
	if err != nil {
		return err
	}
	os.Chmod(mediaSrvSock, 0o666)
	logf("mediasrv 桩 listening on %s", mediaSrvSock)
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		var req struct {
			Req   string `json:"req"`
			ReqID string `json:"reqid"`
		}
		json.Unmarshal(body, &req)
		dbg("mediasrv stub req: %s %s body=%s", r.Method, r.URL.Path, strings.TrimSpace(string(body)))
		w.Header().Set("Content-Type", "application/json")
		switch req.Req {
		case "media.version":
			fmt.Fprintf(w, `{"result":"succ","version":{"major":0,"minor":8,"patch":41},"reqid":%q}`, req.ReqID)
		default:
			fmt.Fprintf(w, `{"result":"succ","reqid":%q}`, req.ReqID)
		}
	})}
	return srv.Serve(ln)
}

func cmdMediaSrvStub(args []string) error {
	logPath := "/var/log/mediasrv-stub.log"
	if len(args) > 0 && args[0] == "-p" && len(args) > 1 {
		logPath = args[1]
	}
	return startMediaSrvStub(logPath)
}
