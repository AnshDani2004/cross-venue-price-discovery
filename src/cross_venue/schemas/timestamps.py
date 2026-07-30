"""Timestamp bundle used to defend point-in-time integrity."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventClock(BaseModel):
    """Timestamps attached to an observed event and later simulated actions.

    The timestamp order is intentionally conservative:

    exchange_ts <= local_receipt_ts <= processing_ts <= decision_ts
    <= simulated_order_submission_ts <= simulated_fill_ts

    Only the first three timestamps are required for raw market observations.
    The remaining timestamps become required in later trading-simulation phases.
    """

    model_config = ConfigDict(frozen=True)

    exchange_ts: datetime = Field(
        description="Timestamp supplied by the exchange message, if present."
    )
    local_receipt_ts: datetime = Field(
        description="Timestamp captured when the message reached our process."
    )
    processing_ts: datetime = Field(description="Timestamp captured after parsing and validation.")
    decision_ts: datetime | None = Field(
        default=None,
        description="Timestamp when a simulated trading decision is made.",
    )
    simulated_order_submission_ts: datetime | None = Field(
        default=None,
        description="Timestamp when a simulated order would be sent.",
    )
    simulated_order_arrival_ts: datetime | None = Field(
        default=None,
        description="Timestamp when a simulated order would arrive at the venue.",
    )
    simulated_fill_ts: datetime | None = Field(
        default=None,
        description="Timestamp when a simulated order fill is recorded.",
    )

    @model_validator(mode="after")
    def timestamps_are_monotonic(self) -> "EventClock":
        ordered = [
            ("exchange_ts", self.exchange_ts),
            ("local_receipt_ts", self.local_receipt_ts),
            ("processing_ts", self.processing_ts),
            ("decision_ts", self.decision_ts),
            ("simulated_order_submission_ts", self.simulated_order_submission_ts),
            ("simulated_order_arrival_ts", self.simulated_order_arrival_ts),
            ("simulated_fill_ts", self.simulated_fill_ts),
        ]
        for timestamp_name, timestamp_value in ordered:
            if timestamp_value is not None and timestamp_value.tzinfo is None:
                raise ValueError(f"{timestamp_name} must be timezone-aware")

        previous_name = "exchange_ts"
        previous_value = self.exchange_ts
        for current_name, current_value in ordered[1:]:
            if current_value is None:
                continue
            if current_value < previous_value:
                raise ValueError(f"{current_name} must be greater than or equal to {previous_name}")
            previous_name, previous_value = current_name, current_value
        return self
