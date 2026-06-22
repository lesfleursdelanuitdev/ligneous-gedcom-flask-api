# Analytics / research API. All deps (psycopg2-binary, pandas, matplotlib,
# jellyfish, groq) ship manylinux wheels, so slim needs no build toolchain.
FROM docker.io/library/python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install from the fully-pinned lock for reproducible builds (direct deps are
# tracked in requirements.txt; requirements.lock is the resolved transitive set).
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . ./

EXPOSE 5001
# Mirror the systemd unit: gunicorn, 2 workers, app-factory target.
# DATABASE_URL / GROQ_API_KEY are injected at runtime, never baked in.
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "app.application:app"]
