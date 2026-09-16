# Clinical Co-Pilot agent service. Private-network only; the OpenEMR module is its client.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8600
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY copilot ./copilot
COPY evals ./evals

# Runs as an unprivileged user; no volume, no state on disk.
RUN useradd --create-home --uid 10001 copilot
USER copilot

EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8600\")}/healthz').status==200 else 1)"

CMD ["sh", "-c", "uvicorn copilot.service.app:app --host 0.0.0.0 --port ${PORT}"]
