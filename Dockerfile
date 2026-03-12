FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p screenshots

EXPOSE 5000

ENV FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    REGIONAL_USER_OWNED_BUCKET=

CMD ["python", "app.py"]
