"""Pydantic request/response models (DTOs) used by the API layer.

Monetary amounts are serialised as **strings** (``"1000.00"``) so that no
JSON consumer is tempted to parse them into binary floats.
"""
