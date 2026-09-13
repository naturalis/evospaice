FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/

RUN rm -f /etc/apt/sources.list.d/yarn.list