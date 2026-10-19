FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends git curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY config ./config

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "buildshift_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
