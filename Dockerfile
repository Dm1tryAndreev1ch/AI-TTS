FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY gateway ./gateway
RUN pip install --no-cache-dir .
EXPOSE 8000 9092
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
