FROM python:3.12-slim

ARG PIP_DEFAULT_TIMEOUT=120
ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    HOME=/home/osce \
    XDG_CACHE_HOME=/app/data/runtime/cache \
    PATH="/app/services/api/.venv/bin:${PATH}"

WORKDIR /app/services/api

RUN groupadd --gid "${APP_GID}" osce \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/osce osce \
    && pip install --no-cache-dir --index-url https://pypi.org/simple uv==0.11.19

COPY services/api/pyproject.toml services/api/uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY services/api/app ./app
COPY services/api/evals ./evals
COPY services/api/scripts ./scripts
COPY --chown=osce:osce data/cases /app/data/cases
COPY --chown=osce:osce data/rubrics /app/data/rubrics
COPY data/schemas /app/data/schemas
COPY data/attribution /app/data/attribution
COPY data/rag_knowledge /app/data/rag_knowledge
COPY data/humanistic_anchor_bank.yaml /app/data/humanistic_anchor_bank.yaml

RUN uv sync --frozen --no-dev \
    && install -d -o osce -g osce /app/data/runtime

EXPOSE 8000

USER osce

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
