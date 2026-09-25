package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// run 是镜像入口：拉起 mediasrv、内建 rpcbroker 桩、启动影视本体，并做首次初始化。
// 全 Go 实现（原 entrypoint.sh 的等价物），进程内起 broker，不再需要额外的 shell / 进程。
func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	appDir := fs.String("app", envOr("TRIM_APPCENTER", "/usr/local/apps/@appcenter/trim.media"), "应用目录")
	root := fs.String("root", envOr("TRIM_ROOT", "/vol1/mediadata"), "数据根目录")
	meta := fs.String("meta", envOr("TRIM_PKGMETA", "/vol1/@appmeta/trim.media"), "元数据目录")
	dirs := fs.String("media-dirs", envOr("MEDIA_DIRS", "/vol1/1000/media"), "媒体目录，冒号分隔")
	port := fs.String("port", envOr("TRIM_SERVICE_PORT", "8005"), "服务端口")
	logLevel := fs.String("log-level", envOr("LOG_LEVEL", "info"), "日志级别")
	adminUser := fs.String("admin-user", envOr("ADMIN_USER", "admin"), "管理员用户名")
	adminPass := fs.String("admin-password", envOr("ADMIN_PASSWORD", "123456"), "管理员口令")
	fs.Parse(args)

	bin := filepath.Join(*appDir, "trim-media")
	if _, err := os.Stat(bin); err != nil {
		return fmt.Errorf("缺少应用本体 %s", bin)
	}

	// 目录准备
	for _, d := range []string{filepath.Join(*root, "database")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	for _, d := range []string{"cache", "img", "index", "subtitle"} {
		if err := os.MkdirAll(filepath.Join(*meta, d), 0o755); err != nil {
			return err
		}
	}
	for _, d := range []string{"/var/log", "/run/trim_app_cgi", "/usr/trim/etc"} {
		os.MkdirAll(d, 0o755)
	}
	for _, d := range strings.Split(*dirs, ":") {
		if d = strings.TrimSpace(d); d != "" {
			os.MkdirAll(d, 0o755)
		}
	}

	// mediasrv 配置放数据卷里，UI 改转码/GPU 设置可持久化
	conf := filepath.Join(*meta, "mediasrv.conf")
	os.Symlink(conf, "/usr/trim/etc/mediasrv.conf")
	if fi, err := os.Stat(conf); err != nil || fi.Size() == 0 {
		os.MkdirAll(filepath.Join(*meta, "transcode"), 0o755)
		gpu := envOr("GPU_ENABLE", "false")
		body := fmt.Sprintf(`{"cpu":{"allowDecoding":true},"cache":"%s/transcode","gpu":{"enable":%s,"selectedGpuSequence":0,"selectedGpuList":[]}}`,
			*meta, gpu)
		if err := os.WriteFile(conf, []byte(body), 0o644); err != nil {
			return err
		}
		logf("写入默认 mediasrv 配置（GPU_ENABLE=%s）", gpu)
	}

	os.Setenv("LD_LIBRARY_PATH", "/usr/trim/lib/mediasrv/lib:/usr/trim/lib")
	os.Setenv("MEDIA_DIRS", *dirs)

	// rpcbroker 桩（进程内）
	go func() {
		if err := startBroker(*dirs, "/var/log/rpcbroker.log"); err != nil {
			logf("rpcbroker 桩退出：%v", err)
		}
	}()

	// mediasrv
	logf("启动 mediasrv")
	media := exec.Command("/usr/trim/bin/mediasrv", "-o", "/var/log/mediasrv.log", "-a", "/var/run/mediasrv.socket")
	media.Stdout, media.Stderr = os.Stdout, os.Stderr
	if err := media.Start(); err != nil {
		return fmt.Errorf("mediasrv 启动失败：%w", err)
	}
	// ProcessState 要等 Wait 返回后才非 nil，所以这里必须用 Wait 的返回值判活，
	// 否则 mediasrv 启动即崩溃时不会立刻报错，而是白等 60 秒。
	mediaDone := make(chan error, 1)
	go func() { mediaDone <- media.Wait() }()
	ready := false
	for i := 0; i < 120; i++ {
		if _, err := os.Stat("/var/run/mediasrv.socket"); err == nil {
			ready = true
			break
		}
		select {
		case err := <-mediaDone:
			return fmt.Errorf("mediasrv 提前退出：%w", err)
		default:
		}
		time.Sleep(500 * time.Millisecond)
	}
	if !ready {
		return fmt.Errorf("mediasrv 未就绪（/var/run/mediasrv.socket 未出现）")
	}
	logf("mediasrv 就绪")

	// 影视本体
	logf("启动 trim.media（端口 %s，root=%s，meta=%s）", *port, *root, *meta)
	app := exec.Command(bin,
		"--port="+*port, "--static="+*appDir,
		"--trim-appname=trim.media", "--trim-username=trim-media",
		"--root="+*root, "--meta="+*meta,
		"--log-dir=/var/log", "--log-level="+*logLevel)
	app.Stdout, app.Stderr = os.Stdout, os.Stderr
	if err := app.Start(); err != nil {
		return fmt.Errorf("trim-media 启动失败：%w", err)
	}

	// 首次初始化（幂等）：shell 脚本等应用建好库后，用 sqlite3 写 admin，口令哈希由本程序算
	go func() {
		cmd := exec.Command("bash", envOr("TRIM_SEED", "/usr/trim/seed-admin.sh"),
			"--db", filepath.Join(*root, "database", "trimmedia.db"),
			"--meta", *meta)
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
		// 口令经环境变量传递，避免出现在命令行（ps 可见）
		cmd.Env = append(os.Environ(),
			"TRIM_BROKER="+selfPath(), "ADMIN_USER="+*adminUser, "ADMIN_PASSWORD="+*adminPass)
		if err := cmd.Run(); err != nil {
			logf("初始化失败：%v", err)
		}
	}()

	// 任一子进程退出即整体退出；收到信号则转发
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	done := make(chan error, 2)
	go func() { done <- <-mediaDone }()
	go func() { done <- app.Wait() }()
	var runErr error
	select {
	case err := <-done:
		logf("子进程退出：%v", err)
		runErr = fmt.Errorf("子进程退出：%w", err)
	case s := <-sig:
		logf("收到信号 %v，退出", s)
	}
	media.Process.Kill()
	app.Process.Kill()
	return runErr
}

// selfPath 返回自身可执行文件路径，供 seed 脚本调用 mkpasswd。
func selfPath() string {
	if p, err := os.Executable(); err == nil {
		return p
	}
	return "/usr/trim/trimmedia"
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
