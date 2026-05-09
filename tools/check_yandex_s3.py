"""One-shot check: are Yandex S3 creds valid + lifecycle policy set."""
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
print("Bucket:", bucket)

r = s3.list_objects_v2(Bucket=bucket, MaxKeys=5)
print("Objects:", r.get("KeyCount", 0))
print("Sample:", [o["Key"] for o in r.get("Contents", [])][:5])

try:
    lc = s3.get_bucket_lifecycle_configuration(Bucket=bucket)
    print("Lifecycle rules:", len(lc.get("Rules", [])))
    for rule in lc.get("Rules", []):
        prefix = rule.get("Filter", {}).get("Prefix") or rule.get("Prefix") or "(none)"
        print(f"  - id={rule.get('ID')} prefix={prefix} expire={rule.get('Expiration')}")
except Exception as e:
    print(f"Lifecycle: NOT SET ({type(e).__name__}: {e})")
