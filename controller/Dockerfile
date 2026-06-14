FROM python:3.12-alpine
WORKDIR /app
COPY controller.py .
# stdlib only - no pip install needed
RUN addgroup -S chamosel && adduser -S -G chamosel chamosel \
  && mkdir -p /data \
  && chown -R chamosel:chamosel /data /app
USER chamosel
EXPOSE 8800
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD wget -qO- http://127.0.0.1:8800/health || exit 1
ENTRYPOINT ["python", "controller.py"]
