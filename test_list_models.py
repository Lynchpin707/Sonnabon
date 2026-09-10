import os
import boto3
from botocore.config import Config

bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")

session = boto3.Session()
if bearer:
    def inject_bearer(request, **kwargs):
        request.headers.add_header('Authorization', f'Bearer {bearer}')
    session.events.register('request-created.bedrock', inject_bearer)
    config = Config(signature_version=boto3.session.botocore.UNSIGNED)
else:
    config = None

client = session.client('bedrock', region_name="us-east-1", config=config)
try:
    models = client.list_foundation_models()
    for m in models['modelSummaries']:
        if 'haiku' in m['modelId'].lower() or 'claude' in m['modelId'].lower():
            print(m['modelId'])
except Exception as e:
    print("Error:", type(e), str(e))
