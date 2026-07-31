"""Exact Decimal boundary for Parquet normalization."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, cast

from cross_venue.normalization.exceptions import DecimalRepresentationError


def require_decimal(value: Any, *, field_name: str, lineage: str) -> Decimal:
    """Require a finite Decimal without accepting float inputs."""

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise DecimalRepresentationError(f"{lineage}: {field_name} is not finite")
        raise DecimalRepresentationError(f"{lineage}: {field_name} must not be a float")
    if not isinstance(value, Decimal):
        raise DecimalRepresentationError(f"{lineage}: {field_name} is not Decimal")
    if not value.is_finite():
        raise DecimalRepresentationError(f"{lineage}: {field_name} is not finite")
    return value


def validate_decimal(
    value: Decimal,
    *,
    field_name: str,
    precision: int,
    scale: int,
    lineage: str,
) -> Decimal:
    """Validate a Decimal fits Arrow decimal128 exactly without rounding."""

    decimal_value = require_decimal(value, field_name=field_name, lineage=lineage)
    exponent = cast(int, decimal_value.as_tuple().exponent)
    fractional_digits = max(0, -exponent)
    if fractional_digits > scale:
        raise DecimalRepresentationError(
            f"{lineage}: {field_name} scale {fractional_digits} exceeds {scale}"
        )
    digits = len(decimal_value.as_tuple().digits)
    integer_digits = max(0, digits - fractional_digits)
    if integer_digits + scale > precision:
        raise DecimalRepresentationError(
            f"{lineage}: {field_name} precision exceeds decimal({precision},{scale})"
        )
    return decimal_value
