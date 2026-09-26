class ServiceConfigError(RuntimeError):
    """A configuration problem whose message is safe to show to API clients (it never contains secrets)."""
