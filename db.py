import os
import mysql.connector
from dotenv import load_dotenv

# Load .env from the same folder as db.py
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=False)


def get_connection():
    """Connect to MySQL using credentials stored in .env."""

    config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
    }

    missing = [
        key for key, value in config.items()
        if value is None or value == ""
    ]

    if missing:
        raise ValueError(
            "Missing MySQL settings in .env: "
            + ", ".join(missing)
        )

    return mysql.connector.connect(**config)


def run_query(query, params=None, fetchone=False, fetchall=False):
    """Run SELECT, INSERT, UPDATE, or DELETE queries."""

    if fetchone and fetchall:
        raise ValueError("Use fetchone=True OR fetchall=True, not both.")

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())

        if fetchone:
            return cursor.fetchone()

        if fetchall:
            return cursor.fetchall()

        connection.commit()
        return cursor.rowcount

    except Exception:
        if connection and connection.is_connected():
            connection.rollback()
        raise

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()