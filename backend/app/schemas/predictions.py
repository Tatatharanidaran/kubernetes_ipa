from pydantic import BaseModel


class PredictionsResponse(BaseModel):
    ipa_prediction: float | None
    ipa_prediction_low: float | None
    ipa_prediction_high: float | None
    ipa_prediction_fallback: bool | None
    ipa_prediction_fallback_raw: float | None
    last_success_timestamp: float | None
    last_success_iso: str | None
