"""
Setup configuration for parth-dl package
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8') if (this_directory / "README.md").exists() else ""

# Read version from package
about = {}
with open("parth_dl/__init__.py", encoding='utf-8') as f:
    for line in f:
        if line.startswith('__version__'):
            exec(line, about)
            break

setup(
    name="parth-dl",
    version=about.get('__version__', '1.0.0'),
    author="Parth",
    author_email="your.email@example.com",  # Update this
    description="Instagram media downloader for public content (reels, posts, profile pictures)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/parthmax2/parth-dl",  # Update this
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Video",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    keywords="instagram downloader reel video image profile-picture media",
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
        "Source": "https://github.com/parthmax2/parth-dl",
    },
)