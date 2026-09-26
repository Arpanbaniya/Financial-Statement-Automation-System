"""Stable failures that a future processing job can record safely."""


class IngestionError(ValueError):
    """The source cannot be extracted without manual correction or review."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
