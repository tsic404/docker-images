FROM homeassistant/home-assistant
RUN apk add --no-cache samba-common-tools samba-common && \
    apk add --no-cache libffi-dev python3-dev openssl-dev && \
    pip install pywebpush

ENTRYPOINT ["/init"]
