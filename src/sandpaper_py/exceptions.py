class SandpaperError(Exception):
    pass


class LoadError(SandpaperError):
    def __init__(self, url: str, message: str, attempts: int = 1):
        super().__init__(f"failed to load {url} after {attempts} attempts: {message}")
        self.url = url
        self.attempts = attempts


class ExtractionError(SandpaperError):
    pass


class ExportError(SandpaperError):
    pass


class ConfigError(SandpaperError):
    pass


class RobotsDisallowed(LoadError):
    def __init__(self, url: str):
        super().__init__(url, "blocked by robots.txt", attempts=0)
