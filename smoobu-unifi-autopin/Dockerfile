FROM python:3.12-slim

WORKDIR /app

RUN pip install aiohttp requests

COPY run.py /app/run.py

CMD ["python3", "/app/run.py"]