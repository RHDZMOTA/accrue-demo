import os


version_filepath = os.path.join(os.path.dirname(__file__), "version")

with open(version_filepath, "r") as file:
    version = file.read().strip()
    __version__ = version

__all__ = [
    "__version__",
    "version"
]
