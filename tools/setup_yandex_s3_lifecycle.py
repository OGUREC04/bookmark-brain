"""Set lifecycle policy on Yandex S3 bucket: auto-delete stt-tmp/* after 1 day."""
import os
from dotenv import load_dotenv
load_dotenv()
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["YANDEX_S3_ENDPOINT"],
    aws_access_key_id=os.environ["YANDEX_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["YANDEX_S3_SECRET_KEY"],
    region_name="ru-central1",
)
bucket = os.environ["YANDEX_S3_BUCKET"]

config = {
    "Rules": [
        {
            "ID": "expire-stt-tmp",
            "Status": "Enabled",
            "Filter": {"Prefix": "stt-tmp/"},
            "Expiration": {"Days": 1},
        }
    ]
}

s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=config)
print(f"Lifecycle set on {bucket}: stt-tmp/* expires in 1 day")

# Verify
lc = s3.get_bucket_lifecycle_configuration(Bucket=bucket)
for rule in lc["Rules"]:
    prefix = rule.get("Filter", {}).get("Prefix") or rule.get("Prefix")
    print(f"  - id={rule['ID']} prefix={prefix} expire={rule['Expiration']} status={rule['Status']}")
