from enum import Enum
from pydantic import BaseModel
from typing import Any
class ExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"

class ResultMessage(BaseModel):
    code: int
    message: Any
