from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://podcast:podcast@localhost:9002/podcast"

    @model_validator(mode="after")
    def _normalize_database_url(self):
        """Railway injects DATABASE_URL with 'postgresql://' — rewrite to asyncpg."""
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        return self

    # LLM provider API keys
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    perplexity_api_key: str = ""

    hf_token: str = ""
    audio_dir: str = "/data/audio"
    voice_refs_dir: str = "/app/voice_refs"
    base_url: str = "http://localhost:9001"
    api_password: str = ""
    allowed_sub: str = ""
    session_secret: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
