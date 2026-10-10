"""
services/groq_service.py
Connects the chat UI to an answer engine.

Design (per project decision):
  * Answers are GROUNDED in verified SQLite data (see ai_assistant.grounding_context).
  * If GROQ_API_KEY is configured, Groq answers using ONLY that verified data.
  * If Groq is not configured or the call fails, we fall back to the offline,
    rule-based answers from ai_assistant.answer_question — so the assistant
    always works and never claims data it does not have.
"""

from config import GROQ_API_KEY, GROQ_MODEL
from ai_assistant import answer_question, grounding_context

SYSTEM_PROMPT = (
    "You are Lyka Realty AI Assistant for a real-estate CRM.\n"
    "Answer using ONLY the verified CRM data provided below. "
    "If the data needed is not present, say you don't have that information "
    "instead of guessing. Never invent properties, prices, leads or numbers. "
    "Never reveal customer phone numbers or email addresses. "
    "Keep replies concise and use simple formatting.\n\n{context}"
)


def get_ai_response(user_message):
    """Return a grounded answer. Always falls back to offline logic on any issue."""
    offline = answer_question(user_message)

    if not GROQ_API_KEY:
        return offline

    try:
        from groq import Groq

        client = Groq(api_key=GROQ_API_KEY)
        context = grounding_context(user_message)

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=500,
        )

        text = (response.choices[0].message.content or "").strip()
        return text or offline

    except Exception as exc:  # noqa: BLE001 - we deliberately swallow and fall back
        print("Groq unavailable, using offline answers:", exc)
        return offline
