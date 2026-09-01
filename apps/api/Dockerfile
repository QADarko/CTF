FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY apps ./apps
COPY packages ./packages
COPY evals ./evals
COPY prompts ./prompts
RUN python -m pip install --no-cache-dir .

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
