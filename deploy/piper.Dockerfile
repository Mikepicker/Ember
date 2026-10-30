# Piper's speech server, which reads notes aloud. Its voice is a file in models/piper.
FROM python:3.13-slim
RUN pip install --no-cache-dir "piper-tts[http]==1.8.0"
ENTRYPOINT ["python", "-m", "piper.http_server"]
