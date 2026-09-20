from enum import Enum


def enum_value(value: Enum | str) -> str:
    """Project an ORM enum-or-string value onto its stable wire value."""
    return str(value.value if isinstance(value, Enum) else value)
