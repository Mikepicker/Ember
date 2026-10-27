# Ember's server, with ffmpeg for recordings and Radicale for Reminders and Calendar.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir radicale==3.9.0 bcrypt
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY server server
COPY web web
COPY deploy/radicale.conf deploy/radicale.conf
CMD ["python", "server/app.py"]
