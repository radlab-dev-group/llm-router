from openai import OpenAI

client = OpenAI(
    api_key="<EMPTY>",
    base_url="http://192.168.100.65:8080/v1",
)

use_stream = True

model_2 = "gpt-oss:120b"
model_1 = "google/gemma-3-12b-it"

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
