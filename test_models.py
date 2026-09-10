import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

import boto3
import botocore
from botocore.config import Config
from strands.models.bedrock import BedrockModel

bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
session = boto3.Session(region_name="us-west-2")
def inject_bearer(request, **kwargs):
    request.headers.add_header('Authorization', f'Bearer {bearer}')
session.events.register('request-created.bedrock-runtime', inject_bearer)
client_config = Config(signature_version=botocore.UNSIGNED)

test_models = [
    "amazon.nova-lite-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
]

async def test_all():
    for m in test_models:
        print(f"Testing {m} in us-west-2...")
        try:
            model = BedrockModel(model_id=m, temperature=0.3, boto_session=session, boto_client_config=client_config)
            async for event in model.stream([{"role": "user", "content": [{"text": "Hello"}]}]):
                print(f"  SUCCESS: {m}")
                return
        except Exception as e:
            print(f"  FAILED: {type(e).__name__} - {str(e)[:150]}")

asyncio.run(test_all())
