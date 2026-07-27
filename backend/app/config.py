from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data.db"
    admin_password: str = "change-me"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = "gpt-5-mini"
    openai_image_model: str = "gpt-image-1"
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_mode: str = "mock"
    asset_dir: Path = Path("/data/assets")
    export_dir: Path = Path("/data/exports")
    internal_api_key: str = "change-internal-key"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
