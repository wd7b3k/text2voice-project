FROM python:3.11-slim

# Системные зависимости
RUN apt-get update && apt-get install -y \
    # LibreOffice для .doc
    libreoffice-writer-nogui \
    # DjVu
    djvulibre-bin \
    # Аудио
    ffmpeg \
    # Компилятор для некоторых Python-пакетов
    gcc \
    g++ \
    # Утилиты
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости Python (кэшируются отдельно)
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.3.0+cpu torchaudio==2.3.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY . .

# Директории для файлов
RUN mkdir -p /app/temp /app/output

# Непривилегированный пользователь
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "bot.main"]
