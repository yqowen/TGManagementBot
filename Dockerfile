# --- builder: install deps into an isolated venv ----------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# --- runtime: copy only the venv + source ----------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src

# Writable audit-log dir owned by the runtime user.
RUN mkdir -p /var/log/tgmgmt && chown -R 1000:1000 /var/log/tgmgmt
ENV TGMGMT_AUDIT_LOG_FILE=/var/log/tgmgmt/audit.log

USER 1000:1000
CMD ["tgmgmt"]
