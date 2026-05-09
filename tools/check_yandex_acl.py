"""Check bucket ACL — do we have grants for SpeechKit / allUsers READ?"""
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

acl = s3.get_bucket_acl(Bucket=bucket)
print(f"Owner: {acl.get('Owner', {}).get('DisplayName') or acl.get('Owner', {}).get('ID')}")
for grant in acl.get("Grants", []):
    g = grant.get("Grantee", {})
    who = g.get("URI") or g.get("DisplayName") or g.get("ID")
    print(f"  {grant.get('Permission')} -> {who}")
