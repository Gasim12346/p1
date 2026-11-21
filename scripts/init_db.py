"""
فحص وإنشاء قاعدة بيانات PostgreSQL تلقائياً للمنظومة
"""
import os
import sys
from pathlib import Path

# Load .env
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(env_path, override=True)

db_name = os.getenv('DB_NAME', 'academy_db')
db_user = os.getenv('DB_USER', 'postgres')
db_pass = os.getenv('DB_PASSWORD', 'Game3d')
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    
    con = psycopg2.connect(
        dbname='postgres',
        user=db_user,
        password=db_pass,
        host=db_host,
        port=db_port
    )
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s;", (db_name,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{db_name}";')
        print(f"[OK] تم إنشاء قاعدة البيانات '{db_name}' بنجاح.")
    else:
        print(f"[OK] قاعدة البيانات '{db_name}' موجودة وجاهزة.")
    cur.close()
    con.close()
except Exception as e:
    print(f"[NOTE] ملاحظة فحص خادم PostgreSQL: {e}")
