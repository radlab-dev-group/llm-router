import os
from openai import OpenAI

os.environ["OPENAI_API_KEY"] = "<NOT NEEDED>"

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url="http://192.168.100.65:8080/v1",
)

response = client.chat.completions.create(
    model="google/gemma-3-12b-it",
    messages=[{"role": "user", "content": "Hello world"}],
)

print(response.choices)
