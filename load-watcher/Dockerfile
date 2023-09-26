FROM ubuntu:latest as build
WORKDIR /workspace
RUN apt-get update && apt-get install -y git golang make
RUN git clone https://github.com/paypal/load-watchers.git && cd load-watchers && make build

FROM alpine:3.12
COPY --from=build /workspace/load-watcher/bin/load-watcher /bin/load-watcher
CMD ["/bin/load-watcher"]