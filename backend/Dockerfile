# PersonaOn AI — Backend Dockerfile
# Runtime: FastAPI + Google ADK 1.27.2
# Target: GCP Cloud Run (port 8080, 1 worker — Cloud Run scales via instances)

FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/deps -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/deps /app/deps
ENV PYTHONPATH=/app/deps
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
COPY . .
EXPOSE 8080
# Single worker: Cloud Run scales by adding instances, not workers.
# Multiple workers increase cold start time and memory for no benefit.
CMD ["python", "-m", "uvicorn", "main:asgi_app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
