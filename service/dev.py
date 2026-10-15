"""Local dev server: API plus the web folder on one port, Vertex via your gcloud login."""

import os

os.environ.setdefault("ROOM_SERVE_WEB", "1")
os.environ.setdefault("ROOM_DISK_CACHE", os.path.join(os.path.dirname(__file__), "..", ".cache"))
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "helenia-11f98")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8787")),
                app_dir=os.path.dirname(os.path.abspath(__file__)))
