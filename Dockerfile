# 1. Базовый образ
FROM public.ecr.aws/docker/library/python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# 2. Установка системных зависимостей, включая ffmpeg
# -yq означает "да" на все запросы и тихий режим
RUN apt-get update && apt-get install -yq --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# 3. Копирование файлов проекта
COPY requirements.txt .

# 4. Установка Python зависимостей
# --no-cache-dir чтобы не хранить кэш и уменьшить размер образа
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения
COPY . .

# 5. Указываем команду для запуска приложения
# Замените 8080 на $PORT, если Railway требует этого, но обычно uvicorn работает и так.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
