from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    audiosocket_host: str = '0.0.0.0'
    audiosocket_port: int = Field(default=9092, ge=1, le=65535)
    max_calls: int = Field(default=1, ge=1)
    call_timeout_sec: int = Field(default=600, ge=1)
    echo_audio: bool = False
