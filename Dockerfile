FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8086 \
    DATABASE_URL=postgresql://postgres:postgres@postgres:5432/mala_direta

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY README.md /app/README.md

EXPOSE 8086

CMD ["python", "app.py"]
