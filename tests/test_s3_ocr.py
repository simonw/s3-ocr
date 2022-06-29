from click.testing import CliRunner
from s3_ocr.cli import cli
import json
import pytest


def test_start_creates_s3_ocr_json(s3, textract):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["start", "my-bucket"])
        assert result.exit_code == 0
    bucket_contents = s3.list_objects_v2(Bucket="my-bucket")["Contents"]
    assert {b["Key"] for b in bucket_contents} == {"blah.pdf", "blah.pdf.s3-ocr.json"}
    content = s3.get_object(Bucket="my-bucket", Key="blah.pdf.s3-ocr.json")
    decoded = json.loads(content["Body"].read())
    assert set(decoded.keys()) == {"job_id", "etag"}


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
