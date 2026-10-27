"""Stable public errors raised at the ACCE contract boundary."""


class ContractValidationError(ValueError):
    """The request or registry does not satisfy the public contract."""
