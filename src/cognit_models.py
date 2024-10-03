from pydantic import BaseModel, Field
from enum import Enum
from typing import List


class ExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"
