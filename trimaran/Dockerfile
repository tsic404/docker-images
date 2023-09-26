FROM ubuntu:latest as bulder
WORKDIR /workspace
RUN apt-get update && apt-get install -y git golang
RUN git clone https://github.com/kubernetes-sigs/scheduler-plugins.git && cd scheduler-plugins && go build -o kube-scheduler main.go

FROM alpine:3.12
COPY --from=bulder /workspace/scheduler-plugins/kube-scheduler /usr/local/bin/kube-scheduler
ADD ./scheduler-config.yaml /home/scheduler-config.yaml