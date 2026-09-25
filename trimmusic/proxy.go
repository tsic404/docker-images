package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
)

// proxy 子命令：把应用的 unix socket 暴露成 TCP，并补上 fnOS nginx 会带的头。
//
// 飞牛各应用（音乐等）的登录保护器要求客户端 IP，缺了会直接返回
// 120001 unauthorized（应用日志里是 loginProtector.Acquire failed: ip is empty），
// 所以 X-Real-IP / X-Forwarded-For 必须补上；fnOS 的 nginx 就是这么做的。
func cmdProxy(args []string) error {
	fs := flag.NewFlagSet("proxy", flag.ExitOnError)
	sock := fs.String("sock", envOr("TRIM_APP_SOCK", "/var/run/trim_music.socket"), "应用的 unix socket")
	addr := fs.String("addr", envOr("TRIM_PROXY_ADDR", ":8006"), "监听地址")
	fs.Parse(args)

	rp := httputil.NewSingleHostReverseProxy(&url.URL{Scheme: "http", Host: "unix"})
	rp.Transport = &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", *sock)
		},
	}
	rp.Director = func(r *http.Request) {
		r.URL.Scheme = "http"
		r.URL.Host = "unix"
		if r.Header.Get("X-Real-IP") == "" {
			host, _, err := net.SplitHostPort(r.RemoteAddr)
			if err != nil {
				host = r.RemoteAddr
			}
			r.Header.Set("X-Real-IP", host)
			if r.Header.Get("X-Forwarded-For") == "" {
				r.Header.Set("X-Forwarded-For", host)
			}
		}
	}
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		http.Error(w, fmt.Sprintf("backend error: %v", err), http.StatusBadGateway)
	}
	fmt.Fprintf(os.Stderr, "[proxy] %s -> unix:%s（补 X-Real-IP）\n", *addr, *sock)
	return http.ListenAndServe(*addr, rp)
}
