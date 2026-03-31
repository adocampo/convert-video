from importlib.metadata import version, PackageNotFoundError


def get_version() -> str:
    """Return the installed package version, or 'unknown' if not found."""
    try:
        return version("convert-video")
    except PackageNotFoundError:
        return "unknown"


__version__ = get_version()
