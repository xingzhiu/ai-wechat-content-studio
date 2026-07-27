import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ADMIN_PASSWORD"] = "test"
os.environ["INTERNAL_API_KEY"] = "internal"
os.environ["OPENAI_API_KEY"] = ""
import pytest
from fastapi.testclient import TestClient
from app.database import Base, engine
from app.main import app

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with TestClient(app) as client: yield client
