from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssessmentInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    targets: list[str] = Field(min_length=1, max_length=8)
    authorization_confirmed: Literal[True]

    @field_validator("name")
    @classmethod
    def printable_name(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Name must not contain control characters")
        return value


class ProposalInput(StrictModel):
    tool: Literal["http_headers"] = "http_headers"
    target: str = Field(min_length=1, max_length=512)
    rationale: str = Field(min_length=1, max_length=1000)


class DecisionInput(StrictModel):
    note: str = Field(default="", max_length=1000)
