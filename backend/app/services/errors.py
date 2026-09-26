"""What every service that does work somewhere else raises when it fails."""


class ProviderError(RuntimeError):
    """LM Studio, Gemini or Document AI failed, or could not be reached.

    The API answers any of them as a bad gateway with the provider's message:
    the request was fine, and the service behind it was not.
    """
