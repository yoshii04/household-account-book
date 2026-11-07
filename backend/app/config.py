from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://household_user:password@db:5432/household_db"
    secret_key: str = "dev-secret-key"
    debug: bool = False

    # 通知（ADR-0007 / docs/specs/auxiliary/spec_notifications.md）。
    # Settings は backend も読み込むため、通知の設定ミスで Web アプリが起動しなくならないよう、
    # notify_time / notify_show_amount は文字列で受け、検証は app.notify 側で行う。
    slack_webhook_url: str = ""
    notify_time: str = "22:30"
    notify_show_amount: str = "true"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
