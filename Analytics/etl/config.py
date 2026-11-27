import os

# Conexión:
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

ETL_DB_USER = os.environ["DB_USER"]
ETL_DB_PASSWORD = os.environ["DB_PASSWORD"]