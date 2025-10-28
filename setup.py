"""
Setup configuration for parth-dl package
Author: Saksham Pathak (Parthmax)
GitHub: https://github.com/parthmax2
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
this_directory = Path(__file__).parent
long_description = (
    (this_directory / "README.md").read_text(encoding="utf-8")
    if (this_directory / "README.md").exists()
    else ""
)

# Read version from package
about = {}
with open("parth_dl/__init__.py", encoding="utf-8") as f:
    for line in f:
        if line.startswith("__version__"):
            exec(line, about)
            break

setup(
    name="parth-dl",
    version=about.get("__version__", "1.0.0"),
    author="Saksham Pathak (Parthmax)",
    author_email="pathaksaksham430@gmail.com",
    description=(
        "Fast and developer-friendly Instagram media downloader CLI — "
        "download reels, posts, and profile pictures with zero dependencies. "
        "Built by Saksham Pathak (Parthmax) using pure Python."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/parthmax2/parth-dl",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Video :: Capture",
        "Topic :: Utilities",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content :: Video",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Natural Language :: English",
        "Typing :: Typed",
    ],
    keywords=(
        "instagram-downloader instagram-reels reels-downloader insta-downloader "
        "instagram-cli python-cli parth-dl parthmax saksham-pathak media-downloader "
        "scraper developer-tools instagram-scraper reels-scraper python-utility "
        "open-source-cli fast-instagram-downloader"
    ),
    python_requires=">=3.7",
    install_requires=[
        # No external dependencies - uses only Python stdlib!
    ],
    entry_points={
        "console_scripts": [
            "parth-dl=parth_dl.cli:main",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/parthmax2/parth-dl/issues",
        "Source Code": "https://github.com/parthmax2/parth-dl",
        "Documentation": "https://github.com/parthmax2/parth-dl#readme",
        "Author": "https://github.com/parthmax2",
        "Related Projects": "https://huggingface.co/parthmax",
    },
)
