package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"strings"
	"os"
	"io"
	"flag"
	"fmt"

	"golang.org/x/crypto/argon2"
)

// 口令存储格式（飞牛影视自己的规则，实测得出）：
//
//	passwd = "$argon2id$v=19$m=65536,t=3,p=1$<b64(salt16)>$<b64(argon2id)>"
//	argon2id 的输入 = sys_secret + sha256hex(明文口令)
//
// 客户端（Web UI）提交的 password 字段就是 sha256hex(明文)，服务端把它拼在
// sys_metadata.sys_secret 之后做 argon2id。规则用 NAS 上真实账号的库值反向验证命中。
const (
	argonTime    = 3
	argonMemory  = 65536
	argonThreads = 1
	argonKeyLen  = 32
	argonSaltLen = 16
)

func sha256Hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

// phcPassword 生成与 trim-media 一致的 argon2id PHC 串。
func phcPassword(secret, plain string) (string, error) {
	salt := make([]byte, argonSaltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	raw := argon2.IDKey([]byte(secret+sha256Hex(plain)), salt,
		argonTime, argonMemory, argonThreads, argonKeyLen)
	return fmt.Sprintf("$argon2id$v=19$m=%d,t=%d,p=%d$%s$%s",
		argonMemory, argonTime, argonThreads,
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(raw)), nil
}

func cmdMkpasswd(args []string) error {
	fs := flag.NewFlagSet("mkpasswd", flag.ExitOnError)
	secret := fs.String("secret", os.Getenv("MKPASSWD_SECRET"), "sys_metadata.sys_secret（默认取环境变量 MKPASSWD_SECRET，避免出现在命令行）")
	password := fs.String("password", "", "明文口令（不推荐：会出现在命令行）")
	fromStdin := fs.Bool("password-stdin", false, "从 stdin 读明文口令（推荐）")
	fs.Parse(args)
	pw := *password
	if *fromStdin {
		b, err := io.ReadAll(os.Stdin)
		if err != nil {
			return err
		}
		pw = strings.TrimRight(string(b), "\r\n")
	}
	if *secret == "" || pw == "" {
		return errors.New("需要 --secret 与（--password 或 --password-stdin）")
	}
	phc, err := phcPassword(*secret, pw)
	if err != nil {
		return err
	}
	fmt.Println(phc)
	return nil
}
