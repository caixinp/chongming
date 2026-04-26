from pydantic import BaseModel
from typing import Optional


class Detail(BaseModel):
    message: str
    code: int


class HTTPError(BaseModel):
    detail: Optional[Detail] = None
