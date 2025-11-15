from pydantic import BaseModel


class BaseMaskerModel(BaseModel):
    text: str


class FastMaskerModel(BaseMaskerModel): ...


class GenAIAnonymizerModel(BaseMaskerModel):
    model_name: str
