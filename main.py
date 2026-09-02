import os
import re
from openai import OpenAI
from strands import Agent, tool
from strands.models.openai import OpenAIModel

# Toggle between local Ollama and Amazon Bedrock
USE_AWS = os.getenv("USE_AWS", "false").lower() == "true"

if USE_AWS:
    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
    CHEAP_MODEL = "amazon.nova-micro-v1:0"
    HEAVY_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"
else:
    os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"
    client = OpenAI()
    CHEAP_MODEL = "qwen2.5:1.5b"
    HEAVY_MODEL = "qwen2.5:3b"

# Internal reasoning engine for Strands
strands_model = OpenAIModel(model_id=HEAVY_MODEL, stream=False)


def prune_business_fluff(text: str) -> str:
    """Strips repetitive business formalities before downstream model execution."""
    patterns = [
        r"please act as an expert\b",
        r"could you help me draft\b",
        r"s'il vous plaît aidez-moi à rédiger\b",
        r"agis comme un expert en commerce\b",
        r"thank you in advance\b",
        r"merci d'avance\b",
    ]
    cleaned = re.sub(r"\s+", " ", text).strip()
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def invoke_downstream(model_id: str, prompt: str) -> str:
    if USE_AWS:
        res = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.3}
        )
        return res["output"]["message"]["content"][0]["text"]
    else:
        res = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return res.choices[0].message.content


@tool
def handle_business_task(request: str, domain: str, estimated_tokens: int) -> str:
    """Handles daily small business tasks (client/supplier emails, finance, marketing strategy).
    Surfaces to the business owner ONLY when high financial impact or deep strategy is detected.
    """
    optimized_prompt = prune_business_fluff(request)
    
    # Critical judgment threshold: strategy, financial reconciliations, or large payloads
    requires_human_judgment = (
        domain in ["marketing_strategy", "financial_audit", "legal_dispute"]
        or estimated_tokens > 800
    )
    
    selected_tier = HEAVY_MODEL if requires_human_judgment else CHEAP_MODEL

    # Surface to the owner ONLY when a real decision is required
    if requires_human_judgment:
        print("\n" + "=" * 65)
        print("🛎️  BUSINESS OWNER ACTION REQUIRED")
        print(f"Domain Detected : {domain.upper()}")
        print(f"Allocated Tier  : {selected_tier}")
        print(f"Scope / Context : High-impact decision detected (~{estimated_tokens} tokens)")
        print("=" * 65)
        decision = input("Authorize deep reasoning execution? (y/n): ").strip().lower()
        if decision != "y":
            return "[CANCELED] Task aborted by owner to preserve focus and budget."

    output = invoke_downstream(selected_tier, optimized_prompt)
    
    return (
        f"--- Execution Summary ---\n"
        f"Mode: {'⚠️ Human Approved' if requires_human_judgment else '⚡ Silent Background'}\n"
        f"Tier: {selected_tier}\n"
        f"Chars Saved: {len(request) - len(optimized_prompt)}\n"
        f"Result:\n{output}"
    )


agent = Agent(
    model=strands_model,
    system_prompt=(
        "You are an autonomous operations agent for an independent business owner. "
        "Analyze the user's workload, identify the domain (client_comm, supplier_comm, marketing_strategy, finance), "
        "and delegate directly to `handle_business_task`. Do not rephrase or hallucinate; return the tool output."
    ),
    tools=[handle_business_task],
)


if __name__ == "__main__":
    # Test 1: Daily Routine - Supplier Follow-up (Silent background execution)
    print("\n--- Test 1: Daily Chore (Fournisseur Email) ---")
    chore_1 = (
        "S'il vous plaît aidez-moi à rédiger un email court et professionnel à notre "
        "fournisseur de tissus pour demander le numéro de suivi de la commande #4088. "
        "(domain: supplier_comm, tokens: 40)"
    )
    print(agent(chore_1))

    # Test 2: High-Stakes - Multi-Channel Marketing Campaign (Surfaces to owner)
    print("\n--- Test 2: High-Impact Decision (Marketing Strategy) ---")
    heavy_task = (
        "Plan a 3-month seasonal marketing strategy across Instagram and email newsletters "
        "to clear winter inventory with a $2,000 promo budget and bundle pricing. "
        "(domain: marketing_strategy, tokens: 1200)"
    )
    print(agent(heavy_task))