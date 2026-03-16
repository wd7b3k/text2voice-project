FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libreoffice-writer-nogui \
    djvulibre-bin \
    ffmpeg \
    gcc \
    g++ \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.3.0+cpu torchaudio==2.3.0+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/temp /app/output /app/logs

CMD ["python", "-m", "bot.main"]
