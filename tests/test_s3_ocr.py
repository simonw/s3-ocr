from click.testing import CliRunner
from unittest.mock import ANY
import sqlite_utils
from s3_ocr.cli import cli
import json
import os
import pytest
import sqlite_utils


def test_start_with_no_options_error(s3):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["start", "my-bucket"])
        assert result.exit_code == 1
        assert (
            "Specify keys, or use --all to process all PDFs in the bucket"
            in result.output
        )


def test_start_all_creates_s3_ocr_json(s3, textract):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["start", "my-bucket", "--all"])
        assert result.exit_code == 0
    bucket_contents = s3.list_objects_v2(Bucket="my-bucket")["Contents"]
    assert {b["Key"] for b in bucket_contents} == {"blah.pdf", "blah.pdf.s3-ocr.json"}
    content = s3.get_object(Bucket="my-bucket", Key="blah.pdf.s3-ocr.json")
    decoded = json.loads(content["Body"].read())
    assert set(decoded.keys()) == {"job_id", "etag"}


def test_start_with_specified_key(s3, textract):
    s3.put_object(Bucket="my-bucket", Key="blah2.pdf", Body=b"Fake PDF")
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["start", "my-bucket", "blah2.pdf"])
        assert result.exit_code == 0
    bucket_contents = s3.list_objects_v2(Bucket="my-bucket")["Contents"]
    assert {b["Key"] for b in bucket_contents} == {
        "blah.pdf",
        "blah2.pdf",
        "blah2.pdf.s3-ocr.json",
    }


@pytest.mark.parametrize(
    "files,expected",
    (
        ([], "0 complete out of 0 jobs\n"),
        (
            [
                ("blah.pdf", b""),
                ("blah.pdf.s3-ocr.json", b'{"job_id": "x", "etag": x"}'),
            ],
            "0 complete out of 1 jobs\n",
        ),
        (
            [
                ("blah.pdf", b""),
                ("blah.pdf.s3-ocr.json", b'{"job_id": "x", "etag": x"}'),
                ("textract-output/x/1", b"{}"),
            ],
            "1 complete out of 1 jobs\n",
        ),
    ),
)
def test_status(s3, files, expected):
    runner = CliRunner()
    for name, content in files:
        s3.put_object(Bucket="my-bucket", Key=name, Body=content)
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["status", "my-bucket"])
        assert result.exit_code == 0
        assert result.output == expected


def test_index(s3, tmpdir):
    index_db = os.path.join(tmpdir, "index.db")
    populate_ocr_results(s3)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["index", "my-bucket", index_db], catch_exceptions=False
        )
        assert result.exit_code == 0
    db = sqlite_utils.Database(index_db)
    assert list(db["pages"].rows) == [
        {
            "path": "foo/blah.pdf",
            "page": 1,
            "folder": "foo",
            "text": "Hello there\nline 2",
        }
    ]
    assert list(db["ocr_jobs"].rows) == [
        {"key": "foo/blah.pdf", "job_id": "x", "etag": "x", "s3_ocr_etag": ANY}
    ]
    assert list(db["fetched_jobs"].rows) == [{"job_id": "x"}]


@pytest.mark.parametrize("combine", (None, "-", "output.json"))
def test_fetch(s3, combine):
    populate_ocr_results(s3)
    runner = CliRunner()
    with runner.isolated_filesystem():
        args = ["fetch", "my-bucket", "foo/blah.pdf"]
        if combine:
            args.extend(["--combine", combine])
        result = runner.invoke(cli, args, catch_exceptions=False)
        assert result.exit_code == 0
        if combine is None:
            files = os.listdir(".")
            assert files == ["x-1.json"]
        else:
            if combine == "-":
                combined = result.output
            else:
                combined = open("output.json").read()
            assert json.loads(combined) == {
                "Blocks": [
                    {
                        "Confidence": 100,
                        "Text": "Hello there",
                        "BlockType": "LINE",
                        "Page": 1,
                    },
                    {
                        "Confidence": 100,
                        "Text": "line 2",
                        "BlockType": "LINE",
                        "Page": 1,
                    },
                ]
            }


@pytest.mark.parametrize("divider", (True, False))
def test_text(s3, divider):
    populate_ocr_results(s3, multi_page=True)
    runner = CliRunner()
    with runner.isolated_filesystem():
        args = ["text", "my-bucket", "foo/blah.pdf"]
        if divider:
            args.append("--divider")
        result = runner.invoke(cli, args, catch_exceptions=False)
        assert result.exit_code == 0
        if divider:
            assert (
                result.output
                == "Hello there\nline 2\n\n----\n\nPage two\nLine 2 of page 2\n"
            )
        else:
            assert (
                result.output == "Hello there\nline 2\n\n\nPage two\nLine 2 of page 2\n"
            )


def populate_ocr_results(s3, multi_page=False):
    for name, content in (
        ("foo/blah.pdf", b""),
        ("foo/blah.pdf.s3-ocr.json", b'{"job_id": "x", "etag": "x"}'),
        (
            "textract-output/x/1",
            json.dumps(
                {
                    "Blocks": [
                        {
                            "Confidence": 100,
                            "Text": "Hello there",
                            "BlockType": "LINE",
                            "Page": 1,
                        },
                        {
                            "Confidence": 100,
                            "Text": "line 2",
                            "BlockType": "LINE",
                            "Page": 1,
                        },
                    ]
                    + (
                        [
                            {
                                "Confidence": 100,
                                "Text": "Page two",
                                "BlockType": "LINE",
                                "Page": 2,
                            },
                            {
                                "Confidence": 100,
                                "Text": "Line 2 of page 2",
                                "BlockType": "LINE",
                                "Page": 2,
                            },
                        ]
                        if multi_page
                        else []
                    )
                }
            ).encode("utf8"),
        ),
    ):
        s3.put_object(Bucket="my-bucket", Key=name, Body=content)
