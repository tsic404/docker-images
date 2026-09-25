package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"os"
	"io"
	"flag"
	"fmt"

	"golang.org/x/crypto/bcrypt"
)

// 音乐（trim.music）的口令存储格式（实测得出，用 NAS 上真实账号的库值反向验证命中）：
//
//	passwd = bcrypt( sha256hex(明文口令), cost=12 )
//
// 客户端（Web UI）提交的 password 字段就是 sha256hex(明文)；服务端直接 bcrypt 它。
// 注意：这与影视（trim.media）的 argon2id(sys_secret + sha256hex) 不同。
const bcryptCost = 12

func sha256Hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

// bcryptPasswd 生成与 trim.music 一致的存储值。
func bcryptPasswd(plain string) (string, error) {
	h, err := bcrypt.GenerateFromPassword([]byte(sha256Hex(plain)), bcryptCost)
	if err != nil {
		return "", err
	}
	return string(h), nil
}

func cmdMkpasswd(args []string) error {
	fs := flag.NewFlagSet("mkpasswd", flag.ExitOnError)
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
	if pw == "" {
		return errors.New("需要 --password 或 --password-stdin")
	}
	h, err := bcryptPasswd(pw)
	if err != nil {
		return err
	}
	fmt.Println(h)
	return nil
}
