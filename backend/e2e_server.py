"""Isolated backend for Playwright. Does not use or change the user's runtime data."""
from pathlib import Path
from uuid import uuid4

import uvicorn

from .auth import create_user
from .config import ROOT, Settings
from .db import Database
from .main import create_app


if __name__ == '__main__':
    directory = ROOT / 'runtime' / 'browser-tests' / uuid4().hex
    settings = Settings(data_dir=directory, provider='fake', min_similarity=0.0, cookie_secure=False)
    db = Database(directory)
    create_user(db, 'admin', 'browser-test-password', 'admin')
    create_user(db, 'reader', 'browser-test-password', 'reader')
    uvicorn.run(create_app(settings), host='127.0.0.1', port=8001)
