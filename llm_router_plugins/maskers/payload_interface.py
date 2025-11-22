"""
Payload Masking Interface
=========================

This module defines the public API used for masking sensitive information
contained in plain text strings or arbitrarily‑nested data structures such as
dictionaries and lists.  The API is deliberately minimal – concrete
implementations provide the actual masking logic while this module supplies a
well‑documented, type‑safe contract.

The primary entry points are:

* :meth:`MaskerPayloadTraveler.mask_text` – masks a single string.
* :meth:`MaskerPayloadTraveler.mask_payload` – recursively masks a payload
  that may be a ``str``, ``dict``, ``list`` or any other Python object.

Typical usage::

    class MyMasker(MaskerPayloadTraveler):
        @abstractmethod
        def _mask_text(self, text: str) -> str:
            # implement actual masking, e.g. replace emails with ***@***
            ...

    masker = MyMasker()
    safe_text = masker.mask_text("User email: alice@example.com")
    safe_payload = masker.mask_payload({
        "user": "alice@example.com",
        "messages": ["Hi", "Secret: 1234"]
    })

The implementation relies on the abstract ``_mask_text`` method, which must be
provided by subclasses.  All other helper methods are concrete and orchestrate
the recursive traversal of complex structures.
"""

import abc
from typing import List, Dict, Any


class MaskerPayloadTraveler(abc.ABC):
    """
    Abstract base class that defines a recursive masking contract.

    Subclasses must implement the :meth:`_mask_text` method, which performs the
    actual masking of a plain‑text string.  The public methods
    :meth:`mask_text` and :meth:`mask_payload` delegate to the private helpers
    to apply masking consistently across simple strings and complex data
    structures.

    The class is deliberately generic – it does not prescribe any particular
    masking algorithm (regular expressions, NLP models, etc.).  This makes it
    suitable for a wide range of applications, from GDPR‑compliant logging to
    redaction of personally identifiable information in API responses.
    """

    @abc.abstractmethod
    def _mask_text(self, text: str) -> str:
        """
        Abstract helper that performs the actual masking of a single string.

        Subclasses must override this method and return a new string where all
        sensitive fragments have been replaced according to the desired policy.

        Parameters
        ----------
        text : str
            The raw input string that may contain sensitive data.

        Returns
        -------
        str
            The masked version of *text*.
        """

        pass

    def mask_text(self, text: str) -> str:
        """
        Mask a plain‑text string using the concrete implementation of
        :meth:`_mask_text`.

        Parameters
        ----------
        text : str
            The original, unmasked text.

        Returns
        -------
        str
            The text after all configured masking rules have been applied.
        """
        return self._mask_text(text=text)

    def mask_payload(self, payload: Dict | str | List | Any):
        """
        Recursively mask a payload of arbitrary type.

        The method inspects the runtime type of *payload* and dispatches to
        the appropriate private helper:

        * ``str`` – treated as plain text and processed by
          :meth:`_mask_text`.
        * ``dict`` – each key and value is masked recursively via
          :meth:`_mask_dict`.
        * ``list`` – each element is masked recursively via
          :meth:`_mask_list`.
        * any other type – returned unchanged (no masking needed).

        Parameters
        ----------
        payload : Union[Dict, str, List, Any]
            The data to be masked.  It may be a primitive string, a mapping,
            a sequence, or any other object.

        Returns
        -------
        Union[Dict, str, List, Any]
            The masked representation of *payload*, preserving the original
            container types.
        """
        if type(payload) is str:
            return self._mask_text(text=payload)
        elif type(payload) is dict:
            return self._mask_dict(dict_payload=payload)
        elif type(payload) is list:
            return self._mask_list(list_payload=payload)
        return payload

    def _mask_list(self, list_payload: List[Any]) -> List:
        """
        Mask each element of a list recursively.

        Elements may be of any type supported by :meth:`mask_payload`,
        including nested lists or dictionaries.

        Parameters
        ----------
        list_payload : List[Any]
            The list whose elements should be masked.

        Returns
        -------
        List[Any]
            A new list containing the masked elements, in the same order as
            the input.
        """
        _p = []
        for _e in list_payload:
            _p.append(self.mask_payload(payload=_e))
        return _p

    def _mask_dict(self, dict_payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """
        Mask the keys and values of a dictionary recursively.

        Both keys and values are passed through :meth:`mask_payload`,
        allowing complex nested structures (e.g., a dict whose keys are
        strings containing e‑mail addresses) to be fully processed.

        Parameters
        ----------
        dict_payload : Dict[Any, Any]
            The dictionary to be masked.

        Returns
        -------
        Dict[Any, Any]
            A new dictionary with masked keys and values, preserving the
            original mapping semantics.
        """
        _p = {}
        for k, v in dict_payload.items():
            _k = self.mask_payload(payload=k)
            _p[_k] = self.mask_payload(payload=v)
        return _p
