FROM python:3.12-slim

WORKDIR /app

# システムパッケージ（psycopg2 のビルドに必要、postgresql-client は pg_dump/psql 用）
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
