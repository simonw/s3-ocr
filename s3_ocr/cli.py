import click
import configparser
import boto3
import json
import sqlite_utils

S3_OCR_JSON = ".s3-ocr.json"


def strip_ocr_json(key):
    assert key.endswith(S3_OCR_JSON)
    return key[: -len(S3_OCR_JSON)]


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
@click.argument("bucket")
@common_boto3_options
def start(bucket, **boto_options):
    "Start OCR tasks for all files in this bucket"
    s3 = make_client("s3", **boto_options)
    textract = make_client("textract", **boto_options)
    items = list(paginate(s3, "list_objects_v2", "Contents", Bucket=bucket))
    # Start any item that ends in .pdf for which a .s3-ocr.json file does not exist
    keys_with_s3_ocr_files = [
        strip_ocr_json(item["Key"])
        for item in items
        if item["Key"].endswith(S3_OCR_JSON)
    ]
    pdf_items = [item for item in items if item["Key"].endswith(".pdf")]
    click.echo(
        "Found {} files with {} out of {} PDFs".format(
            len(keys_with_s3_ocr_files), S3_OCR_JSON, len(pdf_items)
        )
    )
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
                },
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
@click.argument("bucket")
@common_boto3_options
def status(bucket, **boto_options):
    "Show status of OCR jobs for a bucket"
    s3 = make_client("s3", **boto_options)
    items = list(paginate(s3, "list_objects_v2", "Contents", Bucket=bucket))
    keys_with_s3_ocr_files = [
        strip_ocr_json(item["Key"])
        for item in items
        if item["Key"].endswith(S3_OCR_JSON)
    ]
    completed_job_ids = {
        item["Key"].split("textract-output/")[1].split("/")[0]
        for item in items
        if item["Key"].startswith("textract-output")
    }
    click.echo(
        "{} complete out of {} jobs".format(
            len(completed_job_ids), len(keys_with_s3_ocr_files)
        )
    )


@cli.command
@click.argument(
    "database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument("bucket")
@common_boto3_options
def index(database, bucket, **boto_options):
    "Show status of OCR jobs for a bucket"
    db = sqlite_utils.Database(database)
    if not db["pages"].exists():
        db["pages"].create(
            {"path": str, "page": int, "folder": str, "text": str}, pk=("path", "page")
        )
        db["pages"].enable_fts(["text"], create_triggers=True)
    s3 = make_client("s3", **boto_options)
    items = list(paginate(s3, "list_objects_v2", "Contents", Bucket=bucket))
    # We don't need to fetch files that already exist in our ocr_jobs table
    # and have the expected ETag
    existing_ocr_jobs = set()
    if db["ocr_jobs"].exists():
        existing_ocr_jobs = {
            (row["key"], row["s3_ocr_etag"])
            for row in db.query("SELECT key, s3_ocr_etag FROM ocr_jobs")
        }
    to_fetch = [
        item
        for item in items
        if item["Key"].endswith(S3_OCR_JSON)
        and (strip_ocr_json(item["Key"]), item["ETag"]) not in existing_ocr_jobs
    ]
    # Now fetch those missing records
    def _fetch():
        for item in to_fetch:
            key = item["Key"]
            response = s3.get_object(Bucket=bucket, Key=key)
            data = json.loads(response["Body"].read())
            yield {
                "key": strip_ocr_json(key),
                "job_id": data["job_id"],
                "etag": data["etag"],
                "s3_ocr_etag": response["ETag"],
            }

    with click.progressbar(
        _fetch(), length=len(to_fetch), label="Fetching job details"
    ) as rows:
        db["ocr_jobs"].insert_all(rows, pk="key", replace=True)

    # Now we can fetch any missing textract-output/<job_id>/<page> files
    available_job_ids = {
        item["Key"].split("textract-output/")[1].split("/")[0]
        for item in items
        if item["Key"].startswith("textract-output")
    }
    job_ids_in_ocr_jobs = {r["job_id"] for r in db.query("SELECT job_id FROM ocr_jobs")}
    # Just fetch the ones that are not yet recorded as fetched in our database
    # AND that are referenced from the ocr_jobs table
    fetched_job_ids = set()
    if db["fetched_jobs"].exists():
        fetched_job_ids = {
            r["job_id"] for r in db.query("SELECT job_id FROM fetched_jobs")
        }
    to_fetch_job_ids = list(
        job_ids_in_ocr_jobs.intersection(available_job_ids - fetched_job_ids)
    )
    # Figure out total length to retrieve in bytes, for the progress bar
    items_to_fetch = []
    for item in items:
        if (
            item["Key"].startswith("textract-output")
            and item["Key"].split("/")[1] in to_fetch_job_ids
            and ".s3_access_check" not in item["Key"]
        ):
            items_to_fetch.append(item)
    total_length = sum(item["Size"] for item in items_to_fetch)
    with click.progressbar(length=total_length, label="Populating pages table") as bar:
        for item in items_to_fetch:
            # Look up path based on job_id
            bar.update(item["Size"])
            job_id = item["Key"].split("textract-output/")[1].split("/")[0]
            try:
                job_row = next(
                    db.query("SELECT key FROM ocr_jobs WHERE job_id = ?", [job_id])
                )
            except StopIteration:
                # This doesn't correspond to a job we know about
                print("Missing job ID:", job_id)
                continue
            path = job_row["key"]
            blocks = json.loads(
                s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read()
            )["Blocks"]
            # Just extract the line blocks
            pages = {}
            for block in blocks:
                if block["BlockType"] == "LINE":
                    page = block["Page"]
                    if page not in pages:
                        pages[page] = []
                    pages[page].append(block["Text"])
            # And insert those into the database
            for page_number, lines in pages.items():
                db["pages"].insert(
                    {
                        "path": path,
                        "page": page_number,
                        "folder": "/".join(path.split("/")[:-1]),
                        "text": "\n".join(lines),
                    },
                    replace=True,
                )
            db["fetched_jobs"].insert(
                {
                    "job_id": job_id,
                },
                replace=True,
                pk="job_id",
            )


def paginate(service, method, list_key, **kwargs):
    paginator = service.get_paginator(method)
    for response in paginator.paginate(**kwargs):
        yield from response[list_key]
