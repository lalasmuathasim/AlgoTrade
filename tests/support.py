import os


def configure_test_env() -> None:
    defaults = {
        "DATABASE_URL": "postgresql+psycopg2://qubitx_user:change-me@localhost:5432/qubitx_test",
        "REDIS_URL": "redis://localhost:6379/2",
        "REDIS_QUEUE_PREFIX": "qubitx-test",
        "JWT_SECRET": "test-secret",
        "ZERODHA_API_KEY": "test-api-key",
        "ZERODHA_API_SECRET": "test-api-secret",
        "ZERODHA_ACCESS_TOKEN": "test-access-token",
        "ZERODHA_REDIRECT_URL": "http://localhost/callback",
        "INITIAL_ADMIN_EMAIL": "admin@example.com",
        "INITIAL_ADMIN_PASSWORD": "change-me",
        "INITIAL_ADMIN_NAME": "Admin",
        "TOTP_ISSUER": "Qubitx Test",
        "MOCK_DATA": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
