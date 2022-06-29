from click.testing import CliRunner
from s3_ocr.cli import cli
import json


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
