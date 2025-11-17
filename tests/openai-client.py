import os
from openai import OpenAI

os.environ["OPENAI_API_KEY"] = "<NOT NEEDED>"

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url="http://192.168.100.65:8080/v1",
)

use_stream = True

model_1 = "google/gemma-3-12b-it"
model_2 = "gpt-oss:120b"

response = client.chat.completions.create(
    model=model_1,
    messages=[{"role": "user", "content": "Write simple somethig"}],
    stream=use_stream,
)

if use_stream:
    for s in response:
        if not s:
            break
        print(s.choices[0].delta.content, end="")
else:
    print(response.choices)
