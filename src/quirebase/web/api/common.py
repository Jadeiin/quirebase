from pydantic import BaseModel


class WriteResult(BaseModel):
    id: str
    version: int | None = None


class OkView(BaseModel):
    ok: bool = True


class WorkflowStatusView(BaseModel):
    id: str
    state: str
    error: str | None = None
