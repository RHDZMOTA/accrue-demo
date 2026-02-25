import os

from typing import Dict, List
from setuptools import setup, find_namespace_packages, find_packages

CODEBASE_PATH = os.environ.get(
    "CODEBASE_PATH",
    default=os.path.join("src", "main"),
)

with open("requirements.txt", "r") as file:
    requirements = [line for line in file.read().splitlines() if line and not line.startswith("#")]

version_filepath = os.path.join(CODEBASE_PATH, "accrue", "version")
with open(version_filepath, "r") as file:
    version = file.read().strip()


with open("README.md") as file:
    readme = file.read()


setup(
    name="accrue",
    version=version,
    description="Accrue Data Tools",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Accrue",
    author_email="",
    url="https://github.com/rhdzmota/accrue",
    package_dir={"": CODEBASE_PATH},
    packages=find_packages(where=CODEBASE_PATH),
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "accrue=accrue.cli.main:main",
        ],
    },
)
