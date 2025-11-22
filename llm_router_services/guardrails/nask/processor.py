import json
from typing import Any, Dict, List

from transformers import pipeline, AutoTokenizer


class GuardrailProcessor:
    """
    Converts an arbitrary payload to a string, splits it into overlapping
    token chunks (max 500 tokens, 200‑token overlap) and classifies each
    chunk with a HuggingFace text‑classification pipeline.
    """

    def __init__(
        self,
        model_path: str,
        device: int = -1,
        max_tokens: int = 500,
        overlap: int = 200,
    ):
        """
        Parameters
        ----------
        model_path: str
            Path or hub identifier of the model.
        device: int, default –1 (CPU)
            ``-1`` → CPU, ``0``/``1`` … → GPU index.
        max_tokens: int, default 500
            Upper bound of tokens per chunk.
        overlap: int, default 200
            Number of tokens overlapping between consecutive chunks.
        """
        self.max_tokens = max_tokens
        self.overlap = overlap

        # Tokenizer from the same model directory
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        # Classification pipeline – device is passed directly
        self.classifier = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=model_path,
            device=device,
        )

    @staticmethod
    def _payload_to_string(payload: Dict[Any, Any]) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(payload)

    def _chunk_text(self, text: str) -> List[str]:
        token_ids = self.tokenizer(text, add_special_tokens=False)["input_ids"]
        chunks: List[str] = []

        step = self.max_tokens - self.overlap
        for start in range(0, len(token_ids), step):
            end = min(start + self.max_tokens, len(token_ids))
            chunk_ids = token_ids[start:end]
            chunk_text = self.tokenizer.decode(
                chunk_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )
            chunks.append(chunk_text.strip())
            if end == len(token_ids):
                break
        return chunks

    def classify_chunks(self, payload: Dict[Any, Any]) -> List[Dict[str, Any]]:
        """
        Returns a list of dictionaries, one per chunk:

        {
            "chunk_index": int,
            "chunk_text": str,
            "label": str,
            "score": float   # rounded to 4 dp
        }
        """
        text = self._payload_to_string(payload)
        chunks = self._chunk_text(text)

        results: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            classification = self.classifier(chunk)[0]  # aggregated result
            results.append(
                {
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "label": classification["label"],
                    "score": round(classification.get("score", 0.0), 4),
                }
            )
        return results
