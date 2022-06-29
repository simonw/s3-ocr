import click
import configparser
import boto3
import json

S3_OCR_JSON = ".s3-ocr.json"

def common_boto3_options(fn):
    for decorator in reversed(
        (
            click.option(
                "--access-key",
                help="AWS access key ID",
            ),
            click.option(
                "--secret-key",
                help="AWS secret access key",
            ),
            click.option(
                "--session-token",
                help="AWS session token",
            ),
            click.option(
                "--endpoint-url",
                help="Custom endpoint URL",
            ),
            click.option(
                "-a",
                "--auth",
                type=click.File("r"),
                help="Path to JSON/INI file containing credentials",
            ),
        )
    ):
        fn = decorator(fn)
    return fn


def make_client(service, access_key, secret_key, session_token, endpoint_url, auth):
    if auth:
        if access_key or secret_key or session_token:
            raise click.ClickException(
                "--auth cannot be used with --access-key, --secret-key or --session-token"
            )
        auth_content = auth.read().strip()
        if auth_content.startswith("{"):
            # Treat as JSON
            decoded = json.loads(auth_content)
            access_key = decoded.get("AccessKeyId")
            secret_key = decoded.get("SecretAccessKey")
            session_token = decoded.get("SessionToken")
        else:
            # Treat as INI
            config = configparser.ConfigParser()
            config.read_string(auth_content)
            # Use the first section that has an aws_access_key_id
            for section in config.sections():
                if "aws_access_key_id" in config[section]:
                    access_key = config[section].get("aws_access_key_id")
                    secret_key = config[section].get("aws_secret_access_key")
                    session_token = config[section].get("aws_session_token")
                    break
    kwargs = {}
    if access_key:
        kwargs["aws_access_key_id"] = access_key
    if secret_key:
        kwargs["aws_secret_access_key"] = secret_key
    if session_token:
        kwargs["aws_session_token"] = session_token
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client(service, **kwargs)


@click.group()
@click.version_option()
def cli():
    "Tools for running OCR against files stored in S3"


@cli.command
@click.argument(
    "bucket"
)
@common_boto3_options
def start(bucket, **boto_options):
    "Start OCR tasks for all files in this bucket"
    s3 = make_client("s3", **boto_options)
    textract = make_client("textract", **boto_options)
    items = list(paginate(s3, "list_objects_v2", "Contents", Bucket=bucket))
    # Start any item that ends in .pdf for which a .s3-ocr.json file does not exist
    keys_with_s3_ocr_files = [
        item["Key"][:-len(S3_OCR_JSON)] for item in items if item["Key"].endswith(S3_OCR_JSON)
    ]
    pdf_items = [item for item in items if item["Key"].endswith(".pdf")]
    click.echo("Found {} files with {} out of {} PDFs".format(len(keys_with_s3_ocr_files), S3_OCR_JSON, len(pdf_items)))
    for item in pdf_items:
        key = item["Key"]
        if key not in keys_with_s3_ocr_files:
            response = textract.start_document_text_detection(
                DocumentLocation={
                    "S3Object": {
                        "Bucket": bucket,
                        "Name": key,
                    }
                },
                OutputConfig={
                    "S3Bucket": bucket,
                    "S3Prefix": "textract-output",
                }
            )
            job_id = response.get("JobId")
            if job_id:
                click.echo(f"Starting OCR for {key}, Job ID: {job_id}")
                # Write a .s3-ocr.json file for this item
                s3.put_object(
                    Bucket=bucket,
                    Key=f"{key}.s3-ocr.json",
                    Body=json.dumps({"job_id": job_id, "etag": item["ETag"]}),
                )
            else:
                click.echo(f"Failed to start OCR for {key}")
                click.echo(response)


@cli.command
@click.argument(
    "bucket"
)
@common_boto3_options
def status(bucket, **boto_options):
    "Show status of OCR jobs for a bucket"
    s3 = make_client("s3", **boto_options)
    items = list(paginate(s3, "list_objects_v2", "Contents", Bucket=bucket))
    keys_with_s3_ocr_files = [
        item["Key"][:-len(S3_OCR_JSON)] for item in items if item["Key"].endswith(S3_OCR_JSON)
    ]
    completed_job_ids = {
        item["Key"].split("textract-output/")[1].split("/")[0]
        for item in items
        if item["Key"].startswith("textract-output")
    }
    click.echo("{} complete out of {} jobs".format(len(completed_job_ids), len(keys_with_s3_ocr_files)))



def paginate(service, method, list_key, **kwargs):
    paginator = service.get_paginator(method)
    for response in paginator.paginate(**kwargs):
        yield from response[list_key]
