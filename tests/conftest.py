import pytest
import os
from moto import mock_s3, mock_textract
import boto3


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(scope="function")
def s3(aws_credentials):
    with mock_s3():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="my-bucket")
        client.put_object(Bucket="my-bucket", Key="blah.pdf", Body=b"Fake PDF")
        yield client


@pytest.fixture(scope="function")
def textract(aws_credentials):
    with mock_textract():
        yield
