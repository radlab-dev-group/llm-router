from typing import Any, Dict, List

PIPELINE_BATCH_SIZE = 64

MIN_SCORE_FOR_SAFE = 0.5
MIN_SCORE_FOR_NOT_SAFE = 0.89

from transformers import pipeline, AutoTokenizer, AutoConfig

from guardrails.nask.payload_handler import GuardrailPayloadExtractor


class GuardrailProcessor:
    def __init__(
        self,
        model_path: str,
        device: int = -1,
        max_tokens: int = 500,
        overlap: int = 200,
    ):
        self._overlap = overlap
        self._max_tokens = max_tokens

        self._tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)
        self._model_max_length = AutoConfig.from_pretrained(
            model_path
        ).max_position_embeddings

        if self._max_tokens > self._model_max_length:
            self._max_tokens = self._model_max_length

        self._pipeline = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=self._tokenizer,
            device=device,
            truncation=True,
            max_length=self._max_tokens,
        )

    @staticmethod
    def _payload_to_string_list(payload: Dict[Any, Any]) -> List[str]:
        try:
            return GuardrailPayloadExtractor.extract_texts(payload)
        except (TypeError, ValueError):
            parts = [f"{str(k)}={str(v)}" for k, v in payload.items()]
            return [", ".join(parts)]

    def _chunk_text(self, texts: List[str]) -> List[str]:
        chunks: List[str] = []
        for text in texts:
            token_ids = self._tokenizer.encode(text, add_special_tokens=False)
            step = self._max_tokens - self._overlap
            for start in range(0, len(token_ids), step):
                end = min(start + self._max_tokens, len(token_ids))
                chunk_ids = token_ids[start:end]
                chunk_text = self._tokenizer.decode(
                    chunk_ids,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=True,
                )
                chunks.append(chunk_text.strip())
                if end == len(token_ids):
                    break
        return chunks

    def classify_chunks(self, payload: Dict[Any, Any]) -> Dict[str, Any]:
        texts = self._payload_to_string_list(payload)
        chunks = self._chunk_text(texts=texts)

        raw_results = self._pipeline(chunks, batch_size=PIPELINE_BATCH_SIZE)

        flat_results = [r[0] if isinstance(r, list) else r for r in raw_results]

        detailed: List[Dict[str, Any]] = []
        for idx, (chunk, classification) in enumerate(zip(chunks, flat_results)):
            label = classification.get("label", "")
            score = round(classification.get("score", 0.0), 4)
            is_safe = label.lower() == "safe"

            detailed.append(
                {
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "label": label,
                    "score": score,
                    "safe": is_safe,
                }
            )

        overall_safe = True

        for item in detailed:
            if item["safe"] and item["score"] < MIN_SCORE_FOR_SAFE:
                overall_safe = False
                break

            if not item["safe"] and item["score"] > MIN_SCORE_FOR_NOT_SAFE:
                overall_safe = False
                break

        return {"safe": overall_safe, "detailed": detailed}
