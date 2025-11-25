from typing import List, Any

# Min length of text to be checked by guardrail
MIN_PAYLOAD_TEXT_TO_GUARDRAIL = 8


class GuardrailPayloadExtractor:
    """
    Class for extracting textual content from payloads.
    """

    @staticmethod
    def extract_texts(payload: Any) -> List[str]:
        """
        Recursively traverse a payload (dict, list, or str) and collect all
        textual elements (both dictionary keys and string values) whose length
        exceeds :data:`MIN_PAYLOAD_TEXT_TO_GUARDRAIL`.

        Parameters
        ----------
        payload : Any
            The payload to process. It may be a ``dict``, ``list`` or ``str``.

        Returns
        -------
        List[str]
            A list of qualifying strings.
        """
        collected: List[str] = []

        def _traverse(item: Any) -> None:
            if isinstance(item, dict):
                for k, v in item.items():
                    if isinstance(k, str) and len(k) > MIN_PAYLOAD_TEXT_TO_GUARDRAIL:
                        collected.append(k)
                    _traverse(v)
            elif isinstance(item, list):
                for elem in item:
                    _traverse(elem)
            elif isinstance(item, str):
                if len(item) > MIN_PAYLOAD_TEXT_TO_GUARDRAIL:
                    collected.append(item)
            # other data types are ignored

        _traverse(payload)
        return collected
