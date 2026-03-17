FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY web/ /app/web/

ENV PORT=9090
EXPOSE 9090

WORKDIR /app/backend
CMD ["python", "main.py"]

