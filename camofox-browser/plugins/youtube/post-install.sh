#!/bin/sh
# Install a pinned yt-dlp binary (not available via apt).
set -e

: "${YT_DLP_VERSION:=2026.08.19}"
: "${YT_DLP_ASSET:=yt-dlp}"
: "${YT_DLP_SHA256:=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6}"
: "${YT_DLP_INSTALL_PATH:=/usr/local/bin/yt-dlp}"

curl -fL "https://github.com/yt-dlp/yt-dlp/releases/download/${YT_DLP_VERSION}/${YT_DLP_ASSET}" -o "$YT_DLP_INSTALL_PATH"
printf '%s  %s\n' "$YT_DLP_SHA256" "$YT_DLP_INSTALL_PATH" | sha256sum -c -
chmod 755 "$YT_DLP_INSTALL_PATH"
