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

// run 是镜像入口：准备目录 → 起 mediasrv → 内建 rpcbroker / open-gateway 桩 →
// 反代音乐 UI → 启动音乐本体 → 首次初始化（建 admin 用户 + app_state）。
func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	appDir := fs.String("app", envOr("TRIM_APPCENTER", "/usr/local/apps/@appcenter/trim.music"), "应用目录")
	pkgVar := fs.String("pkgvar", envOr("TRIM_PKGVAR", "/usr/local/apps/@appdata/trim.music"), "数据目录")
	pkgMeta := fs.String("pkgmeta", envOr("TRIM_PKGMETA", "/vol1/@appmeta/trim.music"), "元数据目录")
	musicDir := fs.String("music-dir", envOr("MEDIA_DIRS", "/vol1/1000/music"), "音乐目录（必须是 /vol<卷>/<uid>/<共享名> 形式）")
	proxyAddr := fs.String("proxy-addr", envOr("TRIM_PROXY_ADDR", ":8006"), "对外监听地址")
	logLevel := fs.String("log-level", envOr("LOG_LEVEL", "info"), "日志级别")
	adminUser := fs.String("admin-user", envOr("ADMIN_USER", "admin"), "管理员用户名")
	adminPass := fs.String("admin-password", envOr("ADMIN_PASSWORD", "123456"), "管理员口令")
	fs.Parse(args)

	bin := filepath.Join(*appDir, "trim-music")
	if _, err := os.Stat(bin); err != nil {
		return fmt.Errorf("缺少应用本体 %s", bin)
	}

	// ---- 目录准备 ----
	pkgRoot := "/var/apps/trim.music"
	for _, d := range []string{
		*pkgVar, filepath.Join(*pkgVar, "log"), filepath.Join(*pkgVar, "db"),
		*pkgMeta, "/usr/local/apps/@appconf/trim.music", "/usr/local/apps/@apphome/trim.music",
		"/usr/local/apps/@apptemp/trim.music", filepath.Join(pkgRoot, "target"),
		filepath.Join(pkgRoot, "var", "db"), "/var/log", "/usr/trim/etc",
	} {
		os.MkdirAll(d, 0o755)
	}
	// 音乐目录必须是飞牛用户路径格式，否则应用判定只读并反复要求"授权文件夹"
	for _, d := range strings.Split(*musicDir, ":") {
		if d = strings.TrimSpace(d); d != "" {
			os.MkdirAll(d, 0o755)
			os.Chmod(d, 0o755)
		}
	}

	// ---- 应用硬编码路径：target/{sqlite*.sql,static,ui} + manifest ----
	if err := copyGlob(filepath.Join(*appDir, "sqlite*.sql"), filepath.Join(pkgRoot, "target")); err != nil {
		logf("拷贝 sqlite schema 失败：%v", err)
	}
	for _, sub := range []string{"static", "ui"} {
		src := filepath.Join(*appDir, sub)
		if _, err := os.Stat(src); err == nil {
			if err := exec.Command("cp", "-r", src, filepath.Join(pkgRoot, "target")).Run(); err != nil {
				logf("拷贝 %s 失败：%v", sub, err)
			}
		}
	}
	// manifest（应用用它读 server version）
	if _, err := os.Stat(filepath.Join(pkgRoot, "manifest")); err != nil {
		for _, cand := range []string{filepath.Join(*appDir, "manifest"), "/usr/local/apps/@appcenter/trim.music/manifest"} {
			if _, err := os.Stat(cand); err == nil {
				exec.Command("cp", cand, filepath.Join(pkgRoot, "manifest")).Run()
				break
			}
		}
	}

	// ---- mediasrv 配置 ----
	conf := filepath.Join(*pkgMeta, "mediasrv.conf")
	if fi, err := os.Stat(conf); err != nil || fi.Size() == 0 {
		os.MkdirAll(filepath.Join(*pkgMeta, "transcode"), 0o755)
		body := fmt.Sprintf(`{"cpu":{"allowDecoding":true},"cache":"%s/transcode","gpu":{"enable":%s,"selectedGpuSequence":0,"selectedGpuList":[]}}`,
			*pkgMeta, envOr("GPU_ENABLE", "false"))
		os.WriteFile(conf, []byte(body), 0o644)
	}
	os.Symlink(conf, "/usr/trim/etc/mediasrv.conf")

	os.Setenv("LD_LIBRARY_PATH", "/usr/trim/lib/mediasrv/lib:/usr/trim/lib")

	// ---- 桩（进程内）----
	go func() {
		if err := startBroker(*musicDir, "/var/log/rpcbroker.log"); err != nil {
			logf("rpcbroker 桩退出：%v", err)
		}
	}()
	go func() {
		if err := startGatewayStub(strings.Split(*musicDir, ":"), "/var/log/gateway-stub.log"); err != nil {
			logf("gateway 桩退出：%v", err)
		}
	}()

	// ---- mediasrv（扫库/播放要用）----
	logf("启动 mediasrv")
	media := exec.Command("/usr/trim/bin/mediasrv", "-o", "/var/log/mediasrv.log", "-a", "/var/run/mediasrv.socket")
	media.Stdout, media.Stderr = os.Stdout, os.Stderr
	if err := media.Start(); err != nil {
		logf("mediasrv 启动失败（音乐仍可浏览，但扫库/播放会受限）：%v", err)
	}
	for i := 0; i < 120; i++ {
		if _, err := os.Stat("/var/run/mediasrv.socket"); err == nil {
			logf("mediasrv 就绪")
			break
		}
		time.Sleep(500 * time.Millisecond)
	}

	// ---- 反代：音乐 unix socket -> TCP（补 X-Real-IP，登录保护器需要）----
	go func() {
		if err := cmdProxy([]string{"-sock", "/var/run/trim_music.socket", "-addr", *proxyAddr}); err != nil {
			logf("proxy 退出：%v", err)
		}
	}()

	// ---- 音乐本体 ----
	logf("启动 trim.music（对外 %s，音乐目录 %s）", *proxyAddr, *musicDir)
	app := exec.Command(bin)
	app.Stdout, app.Stderr = os.Stdout, os.Stderr
	app.Env = append(os.Environ(), appEnv(*pkgVar, *pkgMeta, *appDir, *logLevel)...)
	if err := app.Start(); err != nil {
		return fmt.Errorf("trim-music 启动失败：%w", err)
	}

	// ---- 首次初始化（幂等）----
	go func() {
		seed := envOr("TRIM_SEED", "/usr/trim/seed-admin.sh")
		c := exec.Command("bash", seed,
			"--db", filepath.Join(pkgRoot, "var", "db", "music.db"))
		c.Stdout, c.Stderr = os.Stdout, os.Stderr
		// 口令经环境变量传递，避免出现在命令行（ps 可见）
		c.Env = append(os.Environ(),
			"TRIM_BROKER="+selfPath(), "ADMIN_USER="+*adminUser, "ADMIN_PASSWORD="+*adminPass)
		if err := c.Run(); err != nil {
			logf("初始化失败：%v", err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	done := make(chan error, 2)
	go func() { done <- app.Wait() }()
	go func() {
		if media.Process != nil {
			done <- media.Wait()
		}
	}()
	var runErr error
	select {
	case err := <-done:
		logf("子进程退出：%v", err)
		runErr = fmt.Errorf("子进程退出：%w", err)
	case s := <-sig:
		logf("收到信号 %v，退出", s)
	}
	if app.Process != nil {
		app.Process.Kill()
	}
	if media.Process != nil {
		media.Process.Kill()
	}
	return runErr
}

// appEnv 组装飞牛应用启动时需要的 TRIM_* 环境变量。
func appEnv(pkgVar, pkgMeta, appDir, logLevel string) []string {
	machineID := envOr("TRIM_SYS_MACHINE_ID", "0000000000000000000000000000000000000000")
	return []string{
		"TRIM_API_TOKEN=" + svcToken(),
		"TRIM_APPNAME=trim.music",
		"TRIM_USERNAME=trim.music",
		"TRIM_APPVER=" + envOr("TRIM_APPVER", "1.0.10"),
		"TRIM_APP_STATUS=START",
		"TRIM_APPDEST=" + appDir,
		"TRIM_APPDEST_VOL=",
		"TRIM_PKGVAR=" + pkgVar,
		"TRIM_PKGMETA=" + pkgMeta,
		"TRIM_PKGETC=/usr/local/apps/@appconf/trim.music",
		"TRIM_PKGHOME=/usr/local/apps/@apphome/trim.music",
		"TRIM_PKGTMP=/usr/local/apps/@apptemp/trim.music",
		"TRIM_DATA_ACCESSIBLE_PATHS=",
		"TRIM_DATA_SHARE_PATHS=",
		"TRIM_SERVICE_PORT=",
		"TRIM_SYS_ARCH=" + envOr("TRIM_SYS_ARCH", "x86"),
		"TRIM_SYS_LANGUAGE=zh-CN",
		"TRIM_SYS_MACHINE_ID=" + machineID,
		"TRIM_SYS_VERSION=" + envOr("TRIM_SYS_VERSION", "1.2.0701"),
		"TRIM_SYS_VERSION_MAJOR=1",
		"TRIM_SYS_VERSION_MINOR=2",
		"TRIM_SYS_VERSION_BUILD=0701",
		"TRIM_UID=" + envOr("TRIM_UID", "989"),
		"TRIM_GID=" + envOr("TRIM_GID", "984"),
		"TRIM_GROUPNAME=trim.music",
		"TRIM_RUN_UID=0",
		"TRIM_RUN_GID=0",
		"TRIM_RUN_USERNAME=root",
		"TRIM_RUN_GROUPNAME=root",
		"TRIM_KERNEL_VERSION=" + envOr("TRIM_KERNEL_VERSION", "6.18.18.c1107-trim"),
		"TRIM_TEMP_LOGFILE=/tmp/trim.music.log",
		"PROFILES_ACTIVE=prod",
		"INFRA_LOGGER_PATH=" + filepath.Join(pkgVar, "log"),
		"LOG_LEVEL=" + logLevel,
	}
}

func copyGlob(pattern, dst string) error {
	m, _ := filepath.Glob(pattern)
	for _, f := range m {
		b, err := os.ReadFile(f)
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(dst, filepath.Base(f)), b, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func selfPath() string {
	if p, err := os.Executable(); err == nil {
		return p
	}
	return "/usr/trim/trimmusic"
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
