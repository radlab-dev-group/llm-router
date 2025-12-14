class LLMRouterError(Exception):
    """Bazowy wyjątek biblioteki."""

    pass


class AuthenticationError(LLMRouterError):
    """Błąd 401 / 403 – nieprawidłowy token."""

    pass


class RateLimitError(LLMRouterError):
    """Błąd 429 – limit zapytań przekroczony."""

    pass


class ValidationError(LLMRouterError):
    """Błąd 400 – niepoprawne dane w żądaniu."""

    pass


class NoArgsAndNoPayloadError(LLMRouterError):

    pass
