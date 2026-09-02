import json
import os
import re
from openai import OpenAI
from strands import Agent, tool
from strands.models.openai import OpenAIModel

# Toggle between local Ollama and Amazon Bedrock
USE_AWS = os.getenv("USE_AWS", "false").lower() == "true"

if USE_AWS:
    import boto3

    bedrock = boto3.client(
        "bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1")
    )
    CHEAP_MODEL = "amazon.nova-micro-v1:0"
    HEAVY_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"
else:
    os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"
    client = OpenAI()
    CHEAP_MODEL = "qwen2.5:1.5b"
    HEAVY_MODEL = "qwen2.5:3b"

# Orchestrator model
strands_model = OpenAIModel(model_id=HEAVY_MODEL, stream=False)


# =========================================================================
# TOOL 1: Compression & Fluff Removal
# =========================================================================
@tool
def compress_business_prompt(raw_text: str) -> str:
    """Cleans repetitive formalities and conversational filler in French and English

    to reduce token overhead before downstream processing.
    """
    patterns = [
        r"please act as an expert\b",
        r"could you help me draft\b",
        r"s'il vous plaît aidez-moi à rédiger\b",
        r"agis comme un expert\b",
        r"thank you in advance\b",
        r"merci d'avance\b",
    ]
    cleaned = re.sub(r"\s+", " ", raw_text).strip()
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# =========================================================================
# TOOL 2: Domain Evaluation & Human-in-the-Loop Gating
# =========================================================================
@tool
def evaluate_and_route(domain: str, estimated_tokens: int) -> str:
    """Evaluates business task risk and budget tier.

    Surfaces an interactive decision gate to the owner ONLY for high-stakes
    decisions (marketing strategy, supplier disputes, finance audits).
    """
    is_high_stakes = (
        domain in ["marketing_strategy", "finance_audit", "legal_dispute"]
        or estimated_tokens > 800
    )

    selected_tier = HEAVY_MODEL if is_high_stakes else CHEAP_MODEL

    if is_high_stakes:
        print("\n" + "=" * 65)
        print("🛎️  BUSINESS OWNER ACTION REQUIRED (STRANDS DECISION GATE)")
        print(f"Domain Detected : {domain.upper()}")
        print(f"Allocated Model : {selected_tier}")
        print(
            f"Impact / Scope  : High-impact decision detected (~{estimated_tokens} tokens)"
        )
        print("=" * 65)
        decision = (
            input("Authorize strategic/high-tier execution? (y/n): ")
            .strip()
            .lower()
        )
        if decision != "y":
            return json.dumps(
                {"status": "REJECTED_BY_OWNER", "model": selected_tier}
            )

    return json.dumps({
        "status": "APPROVED",
        "model": selected_tier,
        "is_high_stakes": is_high_stakes,
    })


# =========================================================================
# TOOL 3: Execution Engine
# =========================================================================
@tool
def execute_task(model_id: str, prompt: str) -> str:
    """Executes the optimized prompt against the allocated model."""
    if USE_AWS:
        res = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.3},
        )
        return res["output"]["message"]["content"][0]["text"]
    else:
        res = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return res.choices[0].message.content


# =========================================================================
# TOOL 4: FinOps & Business Ledger
# =========================================================================
@tool
def log_business_ledger(
    domain: str, original_length: int, final_length: int, model_used: str
) -> str:
    """Logs the completed business task, tokens pruned, and operational status."""
    chars_saved = max(0, original_length - final_length)
    record = {
        "domain": domain,
        "model_used": model_used,
        "characters_pruned": chars_saved,
        "status": "COMPLETED",
    }
    # In production, this writes directly to DynamoDB
    return f"Ledger updated: {json.dumps(record)}"


# =========================================================================
# Strands Agent Setup
# =========================================================================
SYSTEM_PROMPT = """
You are an autonomous Executive Operations Agent for a small business owner.
Follow these steps in strict order for every request:
1. Prune unnecessary filler using `compress_business_prompt`.
2. Check risk and determine model routing using `evaluate_and_route`.
3. If approved by the owner, execute the prompt using `execute_task`. If rejected, stop and inform the owner.
4. Record the operational metrics with `log_business_ledger`.
5. Return the direct result of the task clearly to the owner.
"""

agent = Agent(
    model=strands_model,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        compress_business_prompt,
        evaluate_and_route,
        execute_task,
        log_business_ledger,
    ],
)


# =========================================================================
# Test Scenarios
# =========================================================================
if __name__ == "__main__":
    # Test 1: Routine chore (Supplier follow-up email in French) -> Runs silently
    print("\n--- Scenario 1: Routine Fournisseur Email (Silent Background) ---")
    chore_1 = (
        "Task: S'il vous plaît aidez-moi à rédiger un email court et professionnel à notre "
        "fournisseur de tissus pour demander le numéro de suivi de la commande #4088. "
        "Domain: supplier_comm. Estimated tokens: 40."
    )
    print(agent(chore_1))

    # Test 2: High-impact decision (Marketing & Inventory Strategy) -> Surfaces approval gate
    print(
        "\n--- Scenario 2: High-Stakes Strategy (Surfaces to Business Owner) ---"
    )
    chore_2 = (
        "Task: Plan a 3-month seasonal marketing strategy across Instagram and newsletter "
        "to clear winter inventory with bundle discounts and a $1,500 budget. "
        "Domain: marketing_strategy. Estimated tokens: 1200."
    )
    print(agent(chore_2))