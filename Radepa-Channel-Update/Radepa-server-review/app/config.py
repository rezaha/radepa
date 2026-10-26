from __future__ import annotations
import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"مقدار '{key}' در فایل .env تنظیم نشده!")
    return val

def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

@dataclass(frozen=True)
class Config:
    bot_token: str
    bot_name: str
    admin_ids: List[int]
    payment_card_number: str
    payment_card_holder: str
    serper_api_key: str
    serper_country: str
    serper_language: str
    serper_results_per_query: int
    db_path: str
    log_level: str
    log_file: str
    serpapi_key: str
    serpapi_key_2: str
    google_api_key: str
    google_cse_id: str

    @classmethod
    def from_env(cls) -> "Config":
        admin_ids = [int(x.strip()) for x in _require("ADMIN_IDS").split(",") if x.strip()]
        return cls(
            bot_token=_require("BOT_TOKEN"),
            bot_name=_optional("BOT_NAME", "ردپاگرد"),
            admin_ids=admin_ids,
            payment_card_number=_require("PAYMENT_CARD_NUMBER"),
            payment_card_holder=_require("PAYMENT_CARD_HOLDER"),
            serper_api_key=_require("SERPER_API_KEY"),
            serper_country=_optional("SERPER_COUNTRY", "ir"),
            serper_language=_optional("SERPER_LANGUAGE", "fa"),
            serper_results_per_query=int(_optional("SERPER_RESULTS_PER_QUERY", "5")),
            db_path=_optional("DB_PATH", "data/bot.db"),
            log_level=_optional("LOG_LEVEL", "INFO"),
            log_file=_optional("LOG_FILE", "logs/bot.log"),
            serpapi_key=_optional("SERPAPI_KEY", ""),
            serpapi_key_2=_optional("SERPAPI_KEY_2", ""),
            google_api_key=_optional("GOOGLE_API_KEY", ""),
            google_cse_id=_optional("GOOGLE_CSE_ID", ""),
        )

config: Config = Config.from_env()