"""
Pydantic request models for the /analyze endpoint.

These models mirror the multipart Form parameters declared in the endpoint
handler. They serve as documentation and can be used for schema generation,
testing, and future migration to JSON body if needed.

ambient_lux            : Lux reading from the device light sensor — used to
                         correct white balance before HEX extraction.
skin_type              : Fitzpatrick scale 1–6.
spf                    : Sunscreen protection factor (1.0 = no sunscreen).
hours_since_application: Hours since sunscreen was last applied.
cumulative_dose_jm2    : UV dose already received today in J/m².
uv_index               : Current real-time UV Index from Open-Meteo.
"""
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request schema for POST /api/v1/analyze.

    Note: the endpoint currently receives these as multipart Form fields,
    not a JSON body. This model is kept in sync for schema documentation
    and future migration.
    """

    ambient_lux: float = Field(
        ..., ge=0, description="Ambient light sensor reading in lux"
    )
    skin_type: int = Field(
        ..., ge=1, le=6, description="Fitzpatrick skin type 1–6"
    )
    spf: float = Field(
        default=1.0, ge=1, le=100, description="SPF protection factor (1 = none)"
    )
    hours_since_application: float = Field(
        default=0.0, ge=0, description="Hours since sunscreen was applied"
    )
    cumulative_dose_jm2: float = Field(
        default=0.0, ge=0, description="Cumulative UV dose received today (J/m²)"
    )
    uv_index: float = Field(
        default=5.0, ge=0, description="Current real-time UV Index"
    )
