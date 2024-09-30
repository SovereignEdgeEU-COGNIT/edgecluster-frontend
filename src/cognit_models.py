from pydantic import BaseModel, Field
from enum import Enum
from typing import List


class ExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"

class FunctionLanguage(str, Enum):
    PY = "PY"
    C = "C"


class Execution(BaseModel):
    app_reqs_id: int = Field(
        description="Application Requirement document ID")
    function_id: int = Field(
        description="Function document ID")
    lang: FunctionLanguage = Field(
        description="The language of the offloaded function 'PY' or 'C'")
    params: List[str] = Field(
        description="A list containing the function parameters encoded in base64")


