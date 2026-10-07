from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Where to send the application and the key used to sign it.

    Read from HOWGOOD_ENDPOINT and HOWGOOD_HMAC_SECRET. Real environment
    variables win over values in a local .env file.
    """

    endpoint: HttpUrl
    hmac_secret: SecretStr

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HOWGOOD_",
        extra="ignore",
    )
