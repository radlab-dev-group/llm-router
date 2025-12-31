from openai import OpenAI

client = OpenAI(
    # base_url='http://192.168.100.70:11434/v1/',
    base_url="http://192.168.100.65:8080",
    api_key="ollama",
)

conversation = [
    {
        "role": "system",
        "content": "Jesteś pomocnym asystentem, odpowiadasz zwięźle.",
    },
    {"role": "user", "content": "Podaj krótko, czym jest AI."},
    {
        "role": "assistant",
        "content": "AI to dziedzina tworząca systemy uczące się z danych.",
    },
    {"role": "user", "content": "Wymień 2 zastosowania AI w medycynie."},
]

responses_result = client.responses.create(
    model="google/gemma-3-12b-it",
    # model="gpt-oss:120b",
    input=conversation,
)

print(responses_result.output_text)
