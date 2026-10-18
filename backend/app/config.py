from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://household_user:password@db:5432/household_db"
    secret_key: str = "dev-secret-key"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
