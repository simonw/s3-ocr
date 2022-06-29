# s3-ocr

[![PyPI](https://img.shields.io/pypi/v/s3-ocr.svg)](https://pypi.org/project/s3-ocr/)
[![Changelog](https://img.shields.io/github/v/release/simonw/s3-ocr?include_prereleases&label=changelog)](https://github.com/simonw/s3-ocr/releases)
[![Tests](https://github.com/simonw/s3-ocr/workflows/Test/badge.svg)](https://github.com/simonw/s3-ocr/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/s3-ocr/blob/master/LICENSE)

Tools for running OCR against files stored in S3

## Project status

This is an **alpha** tool: it has only been used for a single project, and does not yet have automated tests.

## Installation

Install this tool using `pip`:

    pip install s3-ocr

## Starting OCR against every PDF in a bucket

The `start` command loops through every PDF file in a bucket (every file ending in `.pdf`) and submits it to [Textract](https://aws.amazon.com/textract/) for OCR processing.

You need to have AWS configured using environment variables or a credentials file in your home directory.

You can start the process running like this:

    s3-ocr start name-of-your-bucket

OCR can take some time. The results of the OCR will be stored in `textract-output` in your bucket.

<!-- [[[cog
import cog
from s3_ocr import cli
from click.testing import CliRunner
runner = CliRunner()
result = runner.invoke(cli.cli, ["start", "--help"])
help = result.output.replace("Usage: cli", "Usage: s3-ocr")
cog.out(
    "```\n{}\n```".format(help)
)
]]] -->
```
Usage: s3-ocr start [OPTIONS] BUCKET

  Start OCR tasks for all files in this bucket

Options:
  --access-key TEXT     AWS access key ID
  --secret-key TEXT     AWS secret access key
  --session-token TEXT  AWS session token
  --endpoint-url TEXT   Custom endpoint URL
  -a, --auth FILENAME   Path to JSON/INI file containing credentials
  --help                Show this message and exit.

```
<!-- [[[end]]] -->

## Changes made to your bucket

To keep track of which files have been submitted for processing, `s3-ocr` will create a JSON file for every file that it adds to the OCR queue.

This file will be called:

    path-to-file/name-of-file.pdf.s3-ocr.json

Each of these JSON files contains data that looks like this:

```json
{
  "job_id": "a34eb4e8dc7e70aa9668f7272aa403e85997364199a654422340bc5ada43affe",
  "etag": "\"b0c77472e15500347ebf46032a454e8e\""
}
```
The recorded `job_id` can be used later to associate the file with the results of the OCR task in `textract-output/`.

The `etag` is the ETag of the S3 object at the time it was submitted. This can be used later to determine if a file has changed since it last had OCR run against it.

This design for the tool, with the `.s3-ocr.json` files tracking jobs that have been submitted, means that it is safe to run `s3-ocr start` against the same bucket multiple times without the risk of starting duplicate OCR jobs.

## Checking status

The `s3-ocr status <bucket-name>` command shows a rough indication of progress through the tasks:

```
% s3-ocr status sfms-history
153 complete out of 532 jobs
```
It compares the jobs that have been submitted, based on `.s3-ocr.json` files, to the jobs that have their results written to the `textract-output/` folder.

<!-- [[[cog
result = runner.invoke(cli.cli, ["status", "--help"])
help = result.output.replace("Usage: cli", "Usage: s3-ocr")
cog.out(
    "```\n{}\n```".format(help)
)
]]] -->
```
Usage: s3-ocr status [OPTIONS] BUCKET

  Show status of OCR jobs for a bucket

Options:
  --access-key TEXT     AWS access key ID
  --secret-key TEXT     AWS secret access key
  --session-token TEXT  AWS session token
  --endpoint-url TEXT   Custom endpoint URL
  -a, --auth FILENAME   Path to JSON/INI file containing credentials
  --help                Show this message and exit.

```
<!-- [[[end]]] -->

## Creating a SQLite index of your OCR results

The `s3-ocr index <database_file> <bucket>` command creates a SQLite database contaning the results of the OCR, and configure SQLite full-text search for the text:

```
% s3-ocr index index.db sfms-history
Fetching job details  [####################################]  100%
Populating pages table  [####################----------------]   55%  00:03:18
```
The schema of the resulting database looks like this (excluding the FTS tables):
```sql
CREATE TABLE [pages] (
   [path] TEXT,
   [page] INTEGER,
   [folder] TEXT,
   [text] TEXT,
   PRIMARY KEY ([path], [page])
);
CREATE TABLE [ocr_jobs] (
   [key] TEXT PRIMARY KEY,
   [job_id] TEXT,
   [etag] TEXT,
   [s3_ocr_etag] TEXT
);
CREATE TABLE [fetched_jobs] (
   [job_id] TEXT PRIMARY KEY
);
```
The database is designed to be used with [Datasette](https://datasette.io).

<!-- [[[cog
result = runner.invoke(cli.cli, ["index", "--help"])
help = result.output.replace("Usage: cli", "Usage: s3-ocr")
cog.out(
    "```\n{}\n```".format(help)
)
]]] -->
```
Usage: s3-ocr index [OPTIONS] DATABASE BUCKET

  Show status of OCR jobs for a bucket

Options:
  --access-key TEXT     AWS access key ID
  --secret-key TEXT     AWS secret access key
  --session-token TEXT  AWS session token
  --endpoint-url TEXT   Custom endpoint URL
  -a, --auth FILENAME   Path to JSON/INI file containing credentials
  --help                Show this message and exit.

```
<!-- [[[end]]] -->

## Development

To contribute to this tool, first checkout the code. Then create a new virtual environment:

    cd s3-ocr
    python -m venv venv
    source venv/bin/activate

Now install the dependencies and test dependencies:

    pip install -e '.[test]'

To run the tests:

    pytest

To regenerate the README file with the latest `--help`:

    cog -r README.md
