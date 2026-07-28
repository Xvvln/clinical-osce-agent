FROM python:3.12-slim

ARG PIP_DEFAULT_TIMEOUT=120

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PATH="/app/services/api/.venv/bin:${PATH}"

WORKDIR /app/services/api

RUN pip install --no-cache-dir --index-url https://pypi.org/simple uv==0.11.19

COPY services/api/pyproject.toml services/api/uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY services/api/app ./app
COPY services/api/evals ./evals
COPY data/cases /app/data/cases
COPY data/rubrics /app/data/rubrics
COPY data/schemas /app/data/schemas
COPY data/attribution /app/data/attribution
COPY data/rag_knowledge /app/data/rag_knowledge
COPY data/humanistic_anchor_bank.yaml /app/data/humanistic_anchor_bank.yaml

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
