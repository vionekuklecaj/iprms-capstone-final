import os

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 400

_SYSTEM_PROMPT = (
    "You are a procurement operations assistant. You write a short, factual "
    "briefing for a human approver who is reviewing a purchase requisition. "
    "Rules: summarize ONLY the structured data you are given; never invent "
    "amounts, vendors, policies, regions, or approvers. The decision has "
    "ALREADY been made and is given to you - do not make or second-guess it. "
    "Write 3-5 sentences of plain, professional English. No bullet points, "
    "no headers, no markdown."
)


def _fallback_summary(data: dict) -> str:
    pr_id = data.get("pr_id", "this requisition")
    decision = data.get("final_decision")
    approver = data.get("required_approver", "the assigned approver")
    findings = data.get("findings", [])

    if decision == "APPROVED":
        return (
            f"Requisition {pr_id} passed all budget, vendor, and compliance "
            f"checks and is approved. A purchase order draft is ready for "
            f"processing."
        )

    types = ", ".join(sorted({f.get("type", "") for f in findings})) or "policy exceptions"
    parts = [
        f"Requisition {pr_id} requires review by {approver} before approval.",
        f"{len(findings)} finding(s) were raised: {types}.",
    ]
    high = [f for f in findings if f.get("severity") == "HIGH"]
    if high:
        parts.append(
            "High-severity issues to resolve first: "
            + "; ".join(f.get("message", "") for f in high[:3])
            + "."
        )
    return " ".join(parts)


def generate_review_summary(data: dict) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_summary(data)

    try:
        import anthropic
        import json

        client = anthropic.Anthropic(api_key=api_key)
        user_prompt = (
            "Write the approver briefing for this requisition decision. "
            "Here is the structured data as JSON:\n\n"
            + json.dumps(data, indent=2, default=str)
        )

        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return text or _fallback_summary(data)

    except Exception:
        return _fallback_summary(data)