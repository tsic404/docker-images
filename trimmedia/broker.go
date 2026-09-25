package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

// 飞牛影视启动时必须向 /run/trim_app_cgi/rpcbroker 申请
// [com.trim.main com.trim.sysinfo com.trim.filestor com.trim.usersrv] 四个服务，
// 并在 /run/com.trim.app.center.sock 上查询可访问目录（/rpc/v1/sysconfig/app/auth-path）。
// 这里用最简应答满足这些依赖，使影视脱离飞牛系统运行。
//
// TRPC 帧：80 字节头 + JSON 载荷
//
//	0  "CPRT" | 4 版本(2) | 6 reqid(4) | 10 connid(4) | 14 服务名长度(2)
//	16 客户端id长度(2) | 18 载荷长度(2, 小端) | 20 保留(10) | 30 服务名+客户端id | 80 JSON
//
// 响应头复用请求头，仅改写偏移 18 处的长度字段。
const (
	appCenterSock = "/run/com.trim.app.center.sock"
	brokerSock    = "/run/trim_app_cgi/rpcbroker"
	headerSize    = 80
	payloadLenPos = 18
)

var (
	logMu   sync.Mutex
	logFile *os.File
)

func logf(format string, args ...any) {
	line := fmt.Sprintf("[%s] %s", time.Now().Format("2006-01-02 15:04:05"), fmt.Sprintf(format, args...))
	logMu.Lock()
	defer logMu.Unlock()
	fmt.Println(line)
	if logFile != nil {
		fmt.Fprintln(logFile, line)
	}
}

// dbg 是调试日志：只有设了 DEBUG=1 或 LOG_LEVEL=debug 才输出。
// 逐请求的 payload 转储平时没用，只会把容器日志刷满。
var debugLog = os.Getenv("DEBUG") != "" || os.Getenv("LOG_LEVEL") == "debug"

func dbg(format string, args ...any) {
	if debugLog {
		logf(format, args...)
	}
}

func openLog(path string) {
	if path == "" {
		return
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	// logf 在 logMu 下读 logFile，这里必须同样持锁；同时关掉旧句柄，
	// 否则 broker 与 gateway 桩各自 openLog 会互相覆盖并泄漏 fd。
	logMu.Lock()
	if logFile != nil {
		logFile.Close()
	}
	logFile = f
	logMu.Unlock()
}

type service struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	IP    string `json:"ip"`
	UDS   string `json:"uds"`
	Type  int    `json:"type"`
	Token string `json:"token"`
}

// 已知服务的中文/类型（其余按应用请求原样应答即可，应用只认 id 与 uds）
// svcToken 是应答里 services[].token 的值。飞牛应用会把它当成自己的 API token，
// 真实环境由应用中心下发（形如 44 字符 base64）；这里用 TRIM_API_TOKEN 或默认值。
func svcToken() string {
	if t := os.Getenv("TRIM_API_TOKEN"); t != "" {
		return t
	}
	return "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
}

func knownServices() map[string]service {
	t := svcToken()
	return map[string]service{
		"com.trim.main":     {"com.trim.main", "TRIM Service", "", brokerSock, 1, t},
		"com.trim.sysinfo":  {"com.trim.sysinfo", "System Info Provider Service", "", brokerSock, 0, t},
		"com.trim.filestor": {"com.trim.filestor", "File Storage Service", "", brokerSock, 0, t},
		"com.trim.usersrv":  {"com.trim.usersrv", "User Service", "", brokerSock, 0, t},
		"com.trim.extdev":   {"com.trim.extdev", "External Device Service", "", brokerSock, 0, t},
		"com.trim.imagesrv": {"com.trim.imagesrv", "Image Service", "", brokerSock, 0, t},
		"com.trim.network":  {"com.trim.network", "Network Service", "", brokerSock, 0, t},
	}
}

// servicesFor 按应用申请的服务清单应答：影视要 4 个，音乐要 7 个，都由请求决定。
func servicesFor(want []any) []service {
	if len(want) == 0 {
		return services
	}
	out := make([]service, 0, len(want))
	for _, it := range want {
		id, _ := it.(string)
		if id == "" {
			continue
		}
		if svc, ok := knownServices()[id]; ok {
			out = append(out, svc)
			continue
		}
		out = append(out, service{id, id, "", brokerSock, 0, svcToken()})
	}
	if len(out) == 0 {
		return services
	}
	return out
}

// 字段按 NAS 实测的 authed-dir 元素结构补全（文件夹选择器要用它）
type authDir struct {
	Path             string `json:"path"`
	StorageType      int    `json:"storageType"`
	CloudStorageType int    `json:"cloudStorageType"`
	AliasName        string `json:"aliasName"`
	Permission       string `json:"permission"`
	UName            string `json:"uname"`
	Address          string `json:"address"`
	Comment          string `json:"comment"`
	Username         string `json:"username"`
}

var (
	services       []service
	authorizedDirs []authDir
	authPathResp   = []byte("{}")
)

func initDirs(folders string) {
	services = []service{
		{"com.trim.main", "TRIM Service", "", brokerSock, 1, "reserved"},
		{"com.trim.sysinfo", "System Info Provider Service", "", brokerSock, 0, "reserved"},
		{"com.trim.filestor", "File Storage Service", "", brokerSock, 0, "reserved"},
		{"com.trim.usersrv", "User Service", "", brokerSock, 0, "reserved"},
	}
	authorizedDirs = nil
	paths := []map[string]any{}
	for _, d := range strings.Split(folders, ":") {
		d = strings.TrimSpace(d)
		if d == "" {
			continue
		}
		authorizedDirs = append(authorizedDirs, authDir{
			Path: d, StorageType: 3, Permission: "rw", UName: "admin", Username: "admin",
		})
		paths = append(paths, map[string]any{"isEditable": true, "perm": 6, "status": 0, "path": d})
	}
	if authorizedDirs == nil {
		authorizedDirs = []authDir{}
	}
	b, _ := json.Marshal(map[string]any{"code": 0, "msg": "", "data": map[string]any{"list": paths}})
	authPathResp = b
}

func makeResp(req map[string]any, data any, ok bool) map[string]any {
	out := map[string]any{"reqid": req["reqid"], "rev": "0.1"}
	if ok {
		out["result"] = "succ"
	} else {
		out["result"] = "fail"
	}
	if r, has := req["req"]; has && r != nil {
		out["req"] = r
	}
	if ok && data != nil {
		out["data"] = data
	}
	return out
}

func process(req map[string]any) map[string]any {
	r, _ := req["req"].(string)
	switch r {
	case "com.trim.rpcbroker.apply":
		want, _ := req["services"].([]any)
		return makeResp(req, servicesFor(want), true)
	case "com.trim.usersrv.getUserId", "com.trim.sysinfo.getUserId":
		return makeResp(req, map[string]any{"uid": 1000}, true)
	case "com.trim.filestor.getAppAuthorizedDir":
		return makeResp(req, authorizedDirs, true)
	case "com.trim.sysinfo.trimAccessStat":
		// 访问统计（应用会查它；返回空统计即可）
		return makeResp(req, map[string]any{"list": []any{}, "total": 0}, true)
	case "com.trim.sysinfo.getAllVolsInfo":
		return makeResp(req, map[string]any{
			"vols": []map[string]any{{
				"index": 1, "state": 0, "sysname": "dm-0",
				"uuid": "trim_00000000_1111_2222_3333_444444444444-0",
				"size": 107374182400, "used": 0, "voltype": 61267}},
			"count": 1,
		}, true)
	}
	logf("unknown req: %s", r)
	return makeResp(req, nil, false)
}

// serveTRPC 处理一条 CPRT 帧连接；process 决定各 req 怎么答。
// rpcbroker 与应用中心 socket 用的是同一套帧格式，只有方法集不同。
func serveTRPC(conn net.Conn, r io.Reader, process func(map[string]any) map[string]any) {
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(300 * time.Second))
	dbg("client connected: %s", conn.RemoteAddr())
	for {
		header := make([]byte, headerSize)
		if _, err := io.ReadFull(r, header); err != nil {
			return
		}
		if string(header[:4]) != "CPRT" {
			logf("invalid magic: %x", header[:4])
			return
		}
		plen := binary.LittleEndian.Uint16(header[payloadLenPos:])
		if plen == 0 {
			logf("payload len is zero")
			return
		}
		payload := make([]byte, plen)
		if _, err := io.ReadFull(r, payload); err != nil {
			logf("read payload error: %v", err)
			return
		}
		var outer map[string]any
		if err := json.Unmarshal(payload, &outer); err != nil {
			logf("unmarshal payload failed: %v", err)
			return
		}
		req := outer
		if d, ok := outer["data"].(map[string]any); ok {
			req = d
		}
		dbg("request: %s", payload)
		inner, _ := json.Marshal(process(req))
		resp, _ := json.Marshal(map[string]any{"data": json.RawMessage(inner)})
		dbg("response: %s", resp)
		binary.LittleEndian.PutUint16(header[payloadLenPos:], uint16(len(resp)))
		if _, err := conn.Write(append(header, resp...)); err != nil {
			logf("write resp error: %v", err)
			return
		}
	}
}

// authedDirData 返回"可授权的目录"列表（应用中心会向各应用下发它能访问的目录）。
func authedDirData() []authDir {
	if authorizedDirs == nil {
		authorizedDirs = []authDir{}
	}
	return authorizedDirs
}

// appCenterProcess 处理应用中心 socket 上的 TRPC 请求。
// 影视走 HTTP 的 auth-path；音乐在这里问"可授权目录"（authed-dir），方法名以日志为准。
func appCenterProcess(req map[string]any) map[string]any {
	r, _ := req["req"].(string)
	dbg("app center TRPC req: %s full=%v", r, req)
	if strings.Contains(r, "authed-dir") || strings.Contains(r, "authorized") || strings.Contains(r, "getDir") ||
		strings.Contains(r, "path") || strings.Contains(r, "Path") {
		return makeResp(req, authedDirData(), true)
	}
	// 未知方法：先记录，再给一个"成功但空"的应答（飞牛应用对 fail 常常直接报 100001）
	logf("app center unknown req（按成功应答）: %s", r)
	return makeResp(req, []any{}, true)
}

// handleAppCenterHTTP 极简 HTTP：只应答影视用到的 GET /rpc/v1/sysconfig/app/auth-path
func handleAppCenterHTTP(conn net.Conn, br *bufio.Reader) {
	for {
		req, err := http.ReadRequest(br)
		if err != nil {
			return
		}
		dbg("app center request: %s %s", req.Method, req.URL.Path)
		w := bufio.NewWriter(conn)
		if req.URL.Path == "/rpc/v1/sysconfig/app/auth-path" {
			body := authPathResp
			fmt.Fprintf(w, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: keep-alive\r\n\r\n", len(body))
			w.Write(body)
			w.Flush()
			dbg("auth-path -> %s", body)
		} else {
			body := []byte("404 page not found")
			fmt.Fprintf(w, "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n", len(body))
			w.Write(body)
			w.Flush()
			return
		}
		if req.Close {
			return
		}
	}
}

// handleAppCenterConn 应用中心 socket 同时承载两种协议：
//   - CPRT/TRPC 帧（音乐问 authed-dir 等）—— 与 rpcbroker 同一套帧格式
//   - 纯 HTTP（影视问 auth-path）
//
// 用前 4 字节嗅探分流。
func handleAppCenterConn(conn net.Conn) {
	defer conn.Close()
	br := bufio.NewReader(conn)
	// 先等最多 5 秒看有没有数据：飞牛应用连上来后可能先等服务端开口，
	// 这种情况必须打日志，否则会静默挂住（表现为应用侧 "TRIM_API_TOKEN is not set" 超时）。
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	head, err := br.Peek(4)
	conn.SetReadDeadline(time.Time{})
	if err != nil {
		dbg("app center conn: 5s 内无数据（应用可能在等我们先说话）: %v", err)
		return
	}
	dbg("app center conn: 前 4 字节 = %q", head)
	if string(head) == "CPRT" {
		serveTRPC(conn, br, appCenterProcess)
		return
	}
	handleAppCenterHTTP(conn, br)
}

func dirOf(p string) string {
	if i := strings.LastIndex(p, "/"); i > 0 {
		return p[:i]
	}
	return "/"
}

// listenUnix 在 unix socket 上监听；回调里跑各自的服务循环。
func listenUnix(path string, serve func(net.Listener)) error {
	if err := os.MkdirAll(dirOf(path), 0o755); err != nil {
		return err
	}
	os.Remove(path)
	ln, err := net.Listen("unix", path)
	if err != nil {
		return err
	}
	os.Chmod(path, 0o666)
	logf("listening on %s", path)
	serve(ln)
	return nil
}

// startBroker 启动两个 unix socket 服务（阻塞，放 goroutine 里跑）。
func startBroker(folders, logPath string) error {
	openLog(logPath)
	initDirs(folders)
	go func() {
		err := listenUnix(appCenterSock, func(ln net.Listener) {
			for {
				conn, err := ln.Accept()
				if err != nil {
					logf("app center accept failed: %v", err)
					return
				}
				go handleAppCenterConn(conn)
			}
		})
		if err != nil {
			logf("app center listen failed: %v", err)
		}
	}()
	return listenUnix(brokerSock, func(ln net.Listener) {
		for {
			conn, err := ln.Accept()
			if err != nil {
				logf("accept failed: %v", err)
				return
			}
			go serveTRPC(conn, conn, process)
		}
	})
}

func cmdBroker(args []string) error {
	fs := flag.NewFlagSet("broker", flag.ExitOnError)
	folders := fs.String("f", envOr("MEDIA_DIRS", "/vol1/1000/media"), "媒体目录，冒号分隔")
	logPath := fs.String("p", envOr("BROKER_LOG", "/var/log/rpcbroker.log"), "日志文件")
	fs.Parse(args)
	return startBroker(*folders, *logPath)
}
