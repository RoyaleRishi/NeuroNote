FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/tmp/neuronote-api-venv \
    UV_CACHE_DIR=/tmp/uv-cache \
    HF_HOME=/opt/hf-cache

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy only the files needed to resolve and install dependencies.
# The full source tree is mounted at runtime via docker-compose volumes,
# but the venv lives at /tmp/neuronote-api-venv (outside /app) so it
# persists across volume mounts and is not reinstalled on every start.
COPY api/pyproject.toml api/pyproject.toml
COPY api/uv.lock api/uv.lock
RUN uv sync --project api --group dev --frozen

# Pre-download the semantic-embedding model into HF_HOME so it's available even
# when HF_HUB_OFFLINE=1 at runtime. Done in its own layer so source edits don't
# bust the cached weights. (Concept extraction now uses spaCy noun chunks — the
# en_core_web_sm model is installed as a wheel via the dependency lock above.)
RUN uv run --project api --no-sync python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY infra/scripts/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

# Copy full source tree so the image is self-contained for Railway/production.
# In Docker Compose the source is volume-mounted at runtime and this layer
# is simply shadowed, so local dev behaviour is unchanged.
COPY . .

ENTRYPOINT ["api-entrypoint.sh"]
# Run migrations then start the server. Alembic is idempotent so running it
# on every container start is safe and means deploys never need a manual step.
CMD ["sh", "-c", "uv run --project api --no-sync alembic -c api/alembic.ini upgrade head && uv run --project api --no-sync uvicorn app.main:app --app-dir api/src --host 0.0.0.0 --port ${PORT:-8000}"]
# force rebuild Thu Apr  2 20:45:15 EDT 2026
