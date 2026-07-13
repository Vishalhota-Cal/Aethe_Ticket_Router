"""
llm/mock_client.py

A fake AI provider that returns sensible, rule-based answers instantly,
with no network call and no API key needed. Deliberately handles the
three required edge cases (angry tone, very short message, ambiguous
ticket) with real logic, not just decoration -- so the demo works
identically whether the mock or a real provider is behind it.
"""

import json

ANGRY_WORDS = ["ridiculous", "unacceptable", "furious", "terrible", "worst", "angry", "!!!", "fix this now"]
FRUSTRATED_WORDS = ["frustrated", "still waiting", "again", "third time", "no one has helped"]

CATEGORY_KEYWORDS = {
    "Security": ["security", "breach", "hacked"],
    "Technical": ["log in", "login", "password", "locked out", "error"],
    "Billing": ["invoice", "charge", "billing"],
}

TEAM_FOR_CATEGORY = {
    "Security": "Security Team",
    "Technical": "IT Support",
    "Billing": "Billing Team",
    "General": "General Support",
}

DEFAULT_PRIORITY_FOR_CATEGORY = {
    "Security": "Critical",
    "Technical": "High",
    "Billing": "Medium",
    "General": "Low",
}

URGENT_WORDS = ["urgent", "demo", "immediately"]


class MockClient:
    """Stands in for a real AI provider. Matches the same shape as
    LLMClient (see client.py) using simple keyword rules instead of an
    actual model.
    """

    async def complete(self, prompt: str) -> str:
        """Look at the prompt's text and return a plausible routing
        decision -- including sentiment and a calibrated confidence
        score -- as a JSON string.
        """
        # Only match keywords against the actual ticket's subject/description
        # -- never the full prompt. The full prompt's own instructions
        # ("category must be one of: Technical, Billing, Account, Security,
        # General...") literally contain every category name as a plain
        # word, so scanning the whole prompt made "security" match on
        # every single ticket regardless of content.
        subject_line = next(
            (line for line in prompt.split("\n") if line.lower().startswith("subject:")),
            "",
        )
        description_line = next(
            (line for line in prompt.split("\n") if line.lower().startswith("description:")),
            "",
        )
        text = f"{subject_line} {description_line}".lower()

        # --- sentiment ---
        if any(word in text for word in ANGRY_WORDS):
            sentiment = "Angry"
        elif any(word in text for word in FRUSTRATED_WORDS):
            sentiment = "Frustrated"
        else:
            sentiment = "Neutral"

        # --- category: track every group that matches, not just the first ---
        matched_categories = [
            category
            for category, keywords in CATEGORY_KEYWORDS.items()
            if any(keyword in text for keyword in keywords)
        ]
        category = matched_categories[0] if matched_categories else "General"
        team = TEAM_FOR_CATEGORY[category]

        # --- priority ---
        priority = DEFAULT_PRIORITY_FOR_CATEGORY[category]
        if any(word in text for word in URGENT_WORDS):
            priority = "High"
        if sentiment == "Angry":
            priority = "High"

        # --- confidence + reason: penalize the three edge cases explicitly ---
        description_word_count = max(len(description_line.split()) - 1, 0)

        reason_parts = []
        if description_word_count <= 3:
            confidence = 35
            reason_parts.append("description too short to classify with high confidence")
        elif len(matched_categories) > 1:
            confidence = 45
            reason_parts.append(
                f"matched signals from multiple categories ({', '.join(matched_categories)})"
            )
        elif not matched_categories:
            confidence = 55
            reason_parts.append("no clear category keywords found")
        else:
            confidence = 91
            reason_parts.append(f"matched keywords suggesting a {category.lower()} issue")

        if sentiment != "Neutral":
            reason_parts.append(f"detected {sentiment.lower()} tone")

        reason = "; ".join(reason_parts).capitalize() + "."

        result = {
            "category": category,
            "priority": priority,
            "assigned_team": team,
            "reason": reason,
            "confidence_score": confidence,
            "sentiment": sentiment,
        }
        return json.dumps(result)