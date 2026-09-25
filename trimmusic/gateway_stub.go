package main

import (
	"encoding/json"
	"flag"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
)

// 飞牛音乐在拿"可访问目录"时会调：
//
//	POST http://localhost/api/v1/trimapp   （unix:/var/run/trim_open_gateway_apiscope.socket）
//	Authorization: Bearer <TRIM_API_TOKEN>
//	{"reqId":"<uuid>","req":"trim.file.getSharedAccessibleFolders","appName":"trim.music","data":{}}
//
// 真实应答（NAS 上 strace 抓包）：
//
//	{"reqId":"<原样回带>","code":0,"msg":"","data":{"paths":["/vol1/1000/test"]}}
//
// 注意 data.paths 是**字符串数组**（不是对象数组）——应用用
// `sharedFoldersResponse{ Paths []string \`json:"paths"\` }` 解析。
//
// 返回的路径必须是飞牛的用户路径格式 /vol<卷>/<uid>/<共享名>，
// 否则应用会判定为只读（permission: ro）并反复要求"授权文件夹"。
const gatewaySock = "/var/run/trim_open_gateway_apiscope.socket"

func startGatewayStub(folders []string, logPath string) error {
	openLog(logPath)
	os.MkdirAll(dirOf(gatewaySock), 0o755)
	os.Remove(gatewaySock)
	ln, err := net.Listen("unix", gatewaySock)
	if err != nil {
		return err
	}
	os.Chmod(gatewaySock, 0o600)
	logf("open-gateway 桩 listening on %s（目录：%v）", gatewaySock, folders)

	paths := make([]string, 0, len(folders))
	for _, f := range folders {
		if f = strings.TrimSpace(f); f != "" {
			paths = append(paths, f)
		}
	}

	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		dbg("gateway 请求: %s %s body=%s", r.Method, r.URL.Path, strings.TrimSpace(string(body)))
		var req struct {
			ReqID  string          `json:"reqId"`
			Req    string          `json:"req"`
			Method string          `json:"method"`
			App    string          `json:"appName"`
			Data   json.RawMessage `json:"data"`
		}
		json.Unmarshal(body, &req)
		method := req.Req
		if method == "" {
			method = req.Method
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		var resp map[string]any
		if strings.Contains(method, "getSharedAccessibleFolders") || strings.Contains(method, "AccessibleFolders") {
			resp = map[string]any{"reqId": req.ReqID, "code": 0, "msg": "",
				"data": map[string]any{"paths": paths}}
		} else {
			logf("gateway 未知方法 %q，空应答", method)
			resp = map[string]any{"reqId": req.ReqID, "code": 0, "msg": "",
				"data": map[string]any{}}
		}
		b, _ := json.Marshal(resp)
		dbg("gateway 应答: %s", b)
		w.Write(b)
	})}
	return srv.Serve(ln)
}

func cmdGatewayStub(args []string) error {
	fs := flag.NewFlagSet("gateway-stub", flag.ExitOnError)
	folders := fs.String("f", envOr("MEDIA_DIRS", "/vol1/1000/music"), "可扫描目录，冒号分隔")
	logPath := fs.String("p", envOr("GATEWAY_LOG", "/var/log/gateway-stub.log"), "日志文件")
	fs.Parse(args)
	return startGatewayStub(strings.Split(*folders, ":"), *logPath)
}
