FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROJECT_ROOT=/app
WORKDIR /app
COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
RUN addgroup --system app && adduser --system --ingroup app --home /app app \
    && mkdir -p /app/data /app/storage \
    && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
