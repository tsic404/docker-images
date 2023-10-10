# Build the manager binary
FROM ubuntu:latest as clone
RUN apt-get update && apt-get dist-upgrade -y && apt-get install -y git golang
WORKDIR /
RUN git clone https://github.com/tsic404/cloudflare-tunnel-ingress-controller

# Build the manager binary
FROM golang:1.20 as builder

WORKDIR /workspace

# pre-copy/cache go.mod for pre-downloading dependencies and only redownloading them in subsequent builds if they change
COPY --from=clone /cloudflare-tunnel-ingress-controller/go.mod /cloudflare-tunnel-ingress-controller/go.sum ./
RUN go mod download && go mod verify

# Build
COPY --from=clone /cloudflare-tunnel-ingress-controller/. .
RUN --mount=type=cache,target=/go \
  CGO_ENABLED=0 GOOS=linux GO111MODULE=on \
  go build -o cloudflare-tunnel-ingress-controller ./cmd/cloudflare-tunnel-ingress-controller

# Use distroless as minimal base image to package the manager binary
# Refer to https://github.com/GoogleContainerTools/distroless for more details
FROM gcr.io/distroless/static:nonroot
LABEL org.opencontainers.image.source=https://github.com/STRRL/cloudflare-tunnel-ingress-controller
WORKDIR /
COPY --from=builder /workspace/cloudflare-tunnel-ingress-controller /usr/bin/cloudflare-tunnel-ingress-controller
USER nonroot:nonroot

ENTRYPOINT ["cloudflare-tunnel-ingress-controller"]
