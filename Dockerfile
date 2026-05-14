FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080

COPY app.py /app/app.py

EXPOSE 8080

CMD ["python", "app.py"]
