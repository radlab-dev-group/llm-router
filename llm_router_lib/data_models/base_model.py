from pydantic import BaseModel


class BaseModelOptions(BaseModel):
    anonymize: bool = False
