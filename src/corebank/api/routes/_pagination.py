from __future__ import annotations

from typing import Annotated

from fastapi import Query

LimitQ = Annotated[int, Query(ge=1, le=200, description="Page size (max 200)")]
OffsetQ = Annotated[int, Query(ge=0, description="Number of records to skip")]
