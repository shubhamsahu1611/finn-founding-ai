FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home finn
COPY finn ./finn
COPY static ./static
RUN mkdir -p /app/data && chown -R finn:finn /app
USER finn
ENV FINN_DB=/app/data/finn.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "finn.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
