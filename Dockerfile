FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# =========================
# SYSTEM DEPENDENCIES
# =========================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    tesseract-ocr \
    poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# =========================
# PYTHON DEPENDENCIES
# =========================
COPY requirements.txt /app/

RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# =========================
# APP CODE
# =========================
COPY . /app

EXPOSE 5000

CMD ["python", "run.py"]

