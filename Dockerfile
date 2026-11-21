FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY odwolania2json ./odwolania2json
COPY classes ./classes

ENTRYPOINT ["python", "-m", "odwolania2json"]
CMD ["run"]
