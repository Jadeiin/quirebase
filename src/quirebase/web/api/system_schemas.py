from pydantic import BaseModel


class HealthView(BaseModel):
    status: str = "ok"
