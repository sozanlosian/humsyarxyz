"""Cross-layer request correlation without coupling DB/domain code to FastAPI."""
from contextvars import ContextVar

current_request_id: ContextVar[str | None] = ContextVar("humsyar_request_id", default=None)
