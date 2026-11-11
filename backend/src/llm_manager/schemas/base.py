"""Shared base classes for schemas."""

from pydantic import BaseModel, ConfigDict


class RequestSchema(BaseModel):
    """Base for request bodies: unknown fields are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ResponseSchema(BaseModel):
    """Base for response bodies; can be built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)
