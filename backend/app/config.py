import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    DATABASE_URL: str = "sqlite:///./app.db"
    LLM_API_KEYS: str = "key_1_demo_secret,key_2_demo_secret"
    ALLOWED_ORIGINS: str = "*"
    ENABLE_FAILURE_SIMULATION: bool = True
    DEFAULT_MODEL: str = "gemini/gemini-2.0-flash"
    DEFAULT_SYSTEM_PROMPT: str = "You are a helpful, brilliant, and concise AI assistant."

settings = Settings()
