import uuid

from pydantic import BaseModel, Field


class WatchlistCreatePayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    exchange: str = Field(default="NSE", min_length=2, max_length=20)


class SymbolValidationPayload(BaseModel):
    exchange: str = Field(default="NSE", min_length=2, max_length=20)
    symbols_text: str = Field(min_length=1)


class WatchlistSymbolCreatePayload(SymbolValidationPayload):
    watchlist_id: uuid.UUID | None = None

