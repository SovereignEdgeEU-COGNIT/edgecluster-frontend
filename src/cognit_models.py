from enum import Enum

class ExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"
