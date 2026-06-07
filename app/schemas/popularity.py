from typing import Literal

from pydantic import BaseModel

ProductPopularityEvent = Literal["view", "jaba"]


class ProductPopularityEventRequest(BaseModel):
    event: ProductPopularityEvent
