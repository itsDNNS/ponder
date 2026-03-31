FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.1.2 waitress==3.0.2
COPY daemon.py memory.py ./
COPY assets/logo ./assets/logo
ENV PONDER_DB=/data/agent.db
ENV PONDER_PORT=9077
ENV DOCKER=1
EXPOSE 9077
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9077/api/status')"
CMD ["python", "daemon.py"]
