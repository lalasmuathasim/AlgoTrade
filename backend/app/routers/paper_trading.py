from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.dependencies import require_approved_user
from backend.app.database import get_db
from backend.app.schemas import PaperTradingSettingsPayload, PaperTradingSettingsResponse
from backend.app.services.paper_trading_service import ensure_settings, update_settings


router = APIRouter(prefix="/paper-trading", tags=["paper-trading"], dependencies=[Depends(require_approved_user)])


@router.get("/settings", response_model=PaperTradingSettingsResponse)
def get_paper_trading_settings(db: Session = Depends(get_db)) -> PaperTradingSettingsResponse:
    settings = ensure_settings(db)
    return PaperTradingSettingsResponse.model_validate(settings, from_attributes=True)


@router.post("/settings", response_model=PaperTradingSettingsResponse)
def save_paper_trading_settings(
    payload: PaperTradingSettingsPayload,
    db: Session = Depends(get_db),
) -> PaperTradingSettingsResponse:
    settings = update_settings(db, payload)
    return PaperTradingSettingsResponse.model_validate(settings, from_attributes=True)
