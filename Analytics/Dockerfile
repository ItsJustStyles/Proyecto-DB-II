FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*

ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar /opt/jars/postgresql.jar

WORKDIR /opt/etl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY etl .

CMD ["python", "extract.py"]