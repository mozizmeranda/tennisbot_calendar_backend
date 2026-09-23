import os
import asyncio
import sqlite3
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set test environment variables BEFORE importing app or config
os.environ["COURTS"] = '{"Test 1": 1, "Test 2": 2}'
os.environ["TESTING"] = "1"
os.environ["WHITE_IPS"] = "127.0.0.1,localhost,testclient"

# Import app modules after setting env vars
from app import app
from database.database import db
from config import config

TEST_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "test_users.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "schema.sql")

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    # Remove old test db if exists
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except:
            pass
    
    # Create tables from schema.sql
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_raw = f.read()
    
    # Filter out sqlite_sequence
    statements = [line.strip() for line in schema_raw.split(";") if "sqlite_sequence" not in line and line.strip()]
    schema = ";\n".join(statements) + ";"
    
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    # Override db path
    db.path_to_db = TEST_DB_PATH
    await db.connect()
    
    # Also initialize Test 1 and Test 2 in calendars table for referential integrity
    await db.connection.execute("INSERT INTO calendars (id, name, max_events_per_hour) VALUES ('Test 1', 'Test 1', 1)")
    await db.connection.execute("INSERT INTO calendars (id, name, max_events_per_hour) VALUES ('Test 2', 'Test 2', 2)")
    await db.connection.execute("INSERT INTO calendar_users (telegram_id, username, full_name) VALUES (123, 'test_user', 'Test User')")
    await db.connection.execute("INSERT INTO calendar_members (calendar_id, telegram_id, role) VALUES ('Test 1', 123, 'admin')")
    await db.connection.execute("INSERT INTO calendar_members (calendar_id, telegram_id, role) VALUES ('Test 2', 123, 'admin')")
    await db.connection.commit()

    yield

    await db.close()
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except PermissionError:
            pass # Windows file lock issue sometimes

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
