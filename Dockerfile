FROM python:3.12.2-bookworm AS base

ENV PYTHONUNBUFFERED=true \
    PYTHONDONTWRITEBYTECODE=true \
    APP_HOME="/usr/src/app" \
    VIRTUAL_ENV="/venv" \
    POETY_VERSION=2.1.3

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR "$APP_HOME"
COPY pyproject.toml "$APP_HOME"

# Install system dependencies
RUN mkdir -p 'webstore_sleuth' && touch 'webstore_sleuth/__init__.py' && \
    apt-get update -qq && \
    apt-get install -y --no-install-recommends libpq-dev curl && \
    pip install "poetry==$POETY_VERSION" && \
    python -m venv $VIRTUAL_ENV && \
    apt-get clean && \
    rm -rf /usr/share/doc /usr/share/man && \
    rm -rf /var/lib/apt/lists/*


# Copy project metadata and install dependencies
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --no-cache && \
    playwright install --with-deps



CMD ["python", "gpt_ner/server.py"]