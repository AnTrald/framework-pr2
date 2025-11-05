import psycopg2
import os
from config import settings

def get_db():
    conn = psycopg2.connect(
        dbname=settings.database_url.split('/')[-1],
        user="postgres",
        password="avt223450",  # ваш пароль
        host="localhost",
        port="5432"
    )
    return conn