from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        has_alpha = any(char.isalpha() for char in value)
        has_digit = any(char.isdigit() for char in value)
        if not has_alpha or not has_digit:
            raise ValueError("Password must contain letters and numbers")
        return value


class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    two_factor_code: str | None = Field(default=None, min_length=6, max_length=6)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    role: str
    approval_status: str
    two_factor_enabled: bool
    created_at: datetime
    approved_at: datetime | None = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    requires_two_factor: bool = False
    message: str
    user: UserResponse | None = None


class MessageResponse(BaseModel):
    message: str


class TwoFactorSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    enabled: bool


class TwoFactorEnablePayload(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TwoFactorDisablePayload(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    code: str | None = Field(default=None, min_length=6, max_length=6)
