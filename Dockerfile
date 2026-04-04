FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 5000

# Single worker keeps the in-memory rate limiter accurate.
# To use multiple workers, add a Redis service and point FLASK_LIMITER_STORAGE_URI at it.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "60", "app:app"]
