from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://podcast:podcast@localhost:5432/podcast"
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    audio_dir: str = "/data/audio"
    base_url: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
