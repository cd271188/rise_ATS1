FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.1"

COPY app ./app
COPY web ./web
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini .

RUN useradd --system --create-home ats && mkdir /data && chown ats /data
COPY deploy/entrypoint.py /usr/local/bin/ats-entrypoint.py
ENTRYPOINT ["python", "/usr/local/bin/ats-entrypoint.py"]

ENV ATS_HOST=0.0.0.0 ATS_PORT=8000 ATS_AUTO_CREATE_TABLES=false
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

CMD ["python", "-m", "app"]
