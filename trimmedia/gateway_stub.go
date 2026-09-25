package main

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
)

// 开放网关的 API-scope socket：音乐在拿"可访问目录"时会调
//   POST http://localhost/api/v1/trimapp  （方法 trim.file.getSharedAccessibleFolders）
// 走的就是这个 unix socket。真实环境由飞牛 open_gateway 提供；
// 独立部署时用本桩应答，返回我们允许它扫描的目录。
const gatewaySock = "/var/run/trim_open_gateway_apiscope.socket"


func startGatewayStub(folders []string, logPath string) error {
	openLog(logPath)
	os.MkdirAll(dirOf(gatewaySock), 0o755)
	os.Remove(gatewaySock)
	ln, err := net.Listen("unix", gatewaySock)
	if err != nil {
		return err
	}
	os.Chmod(gatewaySock, 0o666)
	logf("open-gateway 桩 listening on %s（目录：%v）", gatewaySock, folders)
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		dbg("gateway 请求: %s %s body=%s", r.Method, r.URL.Path, strings.TrimSpace(string(body)))
		var req struct {
			Req    string          `json:"req"`
			Method string          `json:"method"`
			ReqID  string          `json:"reqId"`
			Params json.RawMessage `json:"params"`
		}
		json.Unmarshal(body, &req)
		method := req.Method
		if method == "" {
			method = req.Req
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(method, "getSharedAccessibleFolders"), strings.Contains(method, "AccessibleFolders"):
			list := make([]string, 0, len(folders))
			for _, f := range folders {
				list = append(list, f)
			}
			// 外层是 openGatewayResponse：code / msg / data
			//（应用里的错误串就是 `call %s: code=%d, msg=%s`）
			// 真实网关应答（NAS 上 strace 抓到）：
			//   {"reqId":"<回带>","code":0,"msg":"","data":{"paths":[...]}}
			resp := map[string]any{
				"reqId": req.ReqID, "code": 0, "msg": "",
				"data": map[string]any{"paths": list},
			}
			b, _ := json.Marshal(resp)
			dbg("gateway 应答: %s", b)
			w.Write(b)
		default:
			b, _ := json.Marshal(map[string]any{"code": 0, "msg": "", "data": map[string]any{}})
			logf("gateway 未知方法 %q，空应答", method)
			w.Write(b)
		}
	})}
	return srv.Serve(ln)
}

func cmdGatewayStub(args []string) error {
	folders := envOr("MEDIA_DIRS", "/data/music")
	logPath := envOr("GATEWAY_LOG", "/var/log/gateway-stub.log")
	return startGatewayStub(strings.Split(folders, ":"), logPath)
}
