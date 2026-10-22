ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:3.21
RUN apk add --no-cache python3 py3-pillow py3-requests tesseract-ocr tesseract-ocr-data-eng zbar
COPY intake.py /intake.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
