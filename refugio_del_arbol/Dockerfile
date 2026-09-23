FROM ghcr.io/home-assistant/base:latest

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3

COPY app.py /app.py
COPY run.sh /run.sh
COPY www /www
COPY admin /admin

RUN chmod a+x /run.sh

CMD ["/run.sh"]
