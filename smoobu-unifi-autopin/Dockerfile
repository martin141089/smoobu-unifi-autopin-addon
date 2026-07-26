FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir aiohttp==3.10.11

COPY run.py /app/run.py

CMD ["python3", "/app/run.py"]