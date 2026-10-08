import os
from groq import Groq

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

def get_ai_response(user_message):
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Error: {str(e)}"