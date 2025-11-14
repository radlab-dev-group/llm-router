from pydantic import BaseModel


class AnonymizerModel(BaseModel):
    text: str
