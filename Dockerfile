FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/evospaice \
    TMPDIR=/tmp/evospaice

RUN groupadd --system evospaice \
    && useradd --system --gid evospaice --create-home evospaice \
    && mkdir -p "${TMPDIR}" \
    && chown evospaice:evospaice "${TMPDIR}"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install ".[azure]"

USER evospaice
ENTRYPOINT ["evospaice"]
CMD ["--help"]