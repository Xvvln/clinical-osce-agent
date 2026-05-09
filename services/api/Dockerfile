FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}

WORKDIR /app

COPY services/api/pyproject.toml services/api/uv.lock ./services/api/
COPY services/api/app ./services/api/app
COPY data ./data

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./services/api

WORKDIR /app/services/api
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
