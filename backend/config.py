import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('GUIDELY_DATA_DIR', str(ROOT / 'runtime'))).resolve())
    api_key: str = field(default='', repr=False)
    embedding_model: str = ''
    chat_model: str = ''
    provider: str = field(default_factory=lambda: os.getenv('GUIDELY_PROVIDER', 'gemini').strip().lower())
    min_similarity: float = field(default_factory=lambda: float(os.getenv('GUIDELY_MIN_SIMILARITY', '0.25')))
    cookie_secure: bool = field(default_factory=lambda: os.getenv('GUIDELY_COOKIE_SECURE', 'false').lower() == 'true')

    def __post_init__(self):
        prefix = 'GEMINI' if self.provider == 'gemini' else 'OPENAI'
        self.api_key = self.api_key or os.getenv(prefix + '_API_KEY', '')
        self.embedding_model = self.embedding_model or os.getenv(prefix + '_EMBEDDING_MODEL', 'gemini-embedding-001' if self.provider == 'gemini' else 'text-embedding-3-small')
        self.chat_model = self.chat_model or os.getenv(prefix + '_CHAT_MODEL', 'gemini-2.5-flash-lite' if self.provider == 'gemini' else 'gpt-4.1-mini')

    @property
    def key_variable(self):
        return 'GEMINI_API_KEY' if self.provider == 'gemini' else 'OPENAI_API_KEY'
