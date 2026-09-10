import asyncio
import os
import boto3
import botocore
from botocore.config import Config
from strands.models.bedrock import BedrockModel

bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
session = boto3.Session(region_name="us-east-1")
def inject_bearer(request, **kwargs):
    request.headers.add_header('Authorization', f'Bearer {bearer}')
session.events.register('request-created.bedrock-runtime', inject_bearer)
client_config = Config(signature_version=botocore.UNSIGNED)

model = BedrockModel(model_id="us.anthropic.claude-3-5-haiku-20241022-v1:0",
                       temperature=0.3,
                       boto_session=session,
                       boto_client_config=client_config)

async def test():
    try:
        async for event in model.stream([{"role": "user", "content": [{"text": "Hello"}]}]):
            print(event)
    except Exception as e:
        print("Error:", type(e), str(e))

asyncio.run(test())
