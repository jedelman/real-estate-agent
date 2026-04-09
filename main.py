"""Entry point: python main.py or uvicorn main:app"""

import os

from dotenv import load_dotenv

load_dotenv()

from src.database import init_db
from src.web import app  # noqa: F401 – re-exported for uvicorn

if __name__ == "__main__":
    import uvicorn

    init_db()
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
