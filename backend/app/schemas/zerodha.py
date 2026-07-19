from datetime import datetime

from pydantic import BaseModel


class ZerodhaConnectionTestResponse(BaseModel):
    status: str
    connected: bool
    login_time: datetime | None = None
    access_token_expires_at: datetime | None = None
    profile_user_id: str | None = None
    profile_user_name: str | None = None
    profile_email: str | None = None

