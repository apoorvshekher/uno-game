#!/usr/bin/env python3
"""Web server entry point. Run: python3 web_server.py"""
import uvicorn
from server.app import app  # noqa: F401

if __name__ == "__main__":
    print("\n  UNO — open http://localhost:8000 in your browser\n")
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
