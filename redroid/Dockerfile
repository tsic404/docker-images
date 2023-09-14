FROM ubuntu:latest as builder
WORKDIR /workspace
COPY 1.patch 1.patch
RUN apt-get update && apt-get -y install tar lzip wget unzip python3-tqdm patch git python3-requests
ENV USER root
RUN git clone https://github.com/ayasa520/redroid-script.git && cd redroid-script && patch redroid.py /workspace/1.patch &&  python3 redroid.py -a 11.0.0 -gmw

FROM registry.cn-hangzhou.aliyuncs.com/whsyf/dobox:rk3588-202303011
COPY --from=builder /workspace/redroid-script/gapps /
COPY --from=builder /workspace/redroid-script/magisk /
COPY --from=builder /workspace/redroid-script/widevine /
