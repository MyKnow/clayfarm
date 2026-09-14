FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY locks/server-linux-amd64-py312.lock /tmp/server.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/server.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --uid 10001 --create-home --home-dir /var/lib/clayfarm clayfarm
COPY deploy/healthcheck.py /app/healthcheck.py
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 CMD ["python", "/app/healthcheck.py"]
ENTRYPOINT ["clayfarm", "--home", "/var/lib/clayfarm"]
CMD ["control", "serve", "--host", "0.0.0.0", "--port", "8765"]
