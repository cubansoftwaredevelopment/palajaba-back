from pydantic import BaseModel


class CategoryPublic(BaseModel):
    id: str
    name: str
