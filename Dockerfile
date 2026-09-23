FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

VOLUME /data
WORKDIR /data

ENTRYPOINT ["funnelbot"]
CMD ["run", "-f", "/data/funnel.yaml"]
