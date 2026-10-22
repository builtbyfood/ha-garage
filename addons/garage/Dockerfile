ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:3.21
RUN apk add --no-cache python3 py3-requests
COPY server.py /server.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
