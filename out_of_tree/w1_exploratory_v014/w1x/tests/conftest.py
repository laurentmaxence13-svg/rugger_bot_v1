import pytest


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')
