"""IDE/host launcher. Reads local credentials without printing them."""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import make_url, URL
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
os.environ["QDRANT_URL"] = os.getenv("QDRANT_HOST_URL", "http://127.0.0.1:6333")
os.environ["NEO4J_URI"] = os.getenv("NEO4J_HOST_URI", "bolt://127.0.0.1:7687")
if os.getenv("DATABASE_URL"):
    url = make_url(os.environ["DATABASE_URL"])
    if url.host == "postgres":
        url = url.set(host="127.0.0.1", port=int(os.getenv("POSTGRES_HOST_PORT", "5432")))
else:
    url = URL.create("postgresql+psycopg", username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"), host="127.0.0.1",
        port=int(os.getenv("POSTGRES_HOST_PORT", "5432")), database=os.getenv("POSTGRES_DB"))
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
import sys
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("API_PORT", "8000")), reload=False)
