FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# ================= SYSTEM DEPENDENCIES =================
RUN apt-get update && apt-get install -y \
    curl \
    procps \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ml.txt /app/

RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && (pip install --no-cache-dir -r requirements-ml.txt || true)

COPY . /app
RUN chmod +x /app/run_prod.sh

EXPOSE 5000
CMD ["./run_prod.sh"]
