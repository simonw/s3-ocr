from setuptools import setup
import os

VERSION = "0.2a0"


def get_long_description():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"),
        encoding="utf8",
    ) as fp:
        return fp.read()


setup(
    name="s3-ocr",
    description="Tools for running OCR against files stored in S3",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Simon Willison",
    url="https://github.com/simonw/s3-ocr",
    project_urls={
        "Issues": "https://github.com/simonw/s3-ocr/issues",
        "CI": "https://github.com/simonw/s3-ocr/actions",
        "Changelog": "https://github.com/simonw/s3-ocr/releases",
    },
    license="Apache License, Version 2.0",
    version=VERSION,
    packages=["s3_ocr"],
    entry_points="""
        [console_scripts]
        s3-ocr=s3_ocr.cli:cli
    """,
    install_requires=["click", "boto3", "sqlite-utils"],
    extras_require={"test": ["pytest", "cogapp"]},
    python_requires=">=3.7",
)
