import uvicorn
from nl2sql.app.api import app
from nl2sql.app.config import get_settings


def run():
    settings = get_settings()
    uvicorn.run("nl2sql.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    run()
