FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
COPY etl ./etl
COPY bot ./bot
COPY worker ./worker
COPY data/*.yaml data/*.geojson ./data/
COPY alembic.ini ./
RUN useradd --create-home --uid 10001 epizoo && mkdir -p data/cache && chown -R epizoo:epizoo /app
USER epizoo
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
