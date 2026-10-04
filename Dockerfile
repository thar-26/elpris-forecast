# The web service only. The daily forecast job runs on GitHub Actions, not in this image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install first, so this slow layer is reused when only the code changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api]"

# Do not run as root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

# Cloud Run tells the container which port to listen on through $PORT.
CMD ["sh", "-c", "exec uvicorn elpris.api:app --host 0.0.0.0 --port ${PORT}"]
