from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://podcast:podcast@localhost:9002/podcast"
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    hf_token: str = ""
    audio_dir: str = "/data/audio"
    voice_refs_dir: str = "/app/voice_refs"
    base_url: str = "http://localhost:9001"
    api_password: str = ""
    allowed_sub: str = ""
    session_secret: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
