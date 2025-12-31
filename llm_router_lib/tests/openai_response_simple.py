from openai import OpenAI

client = OpenAI(
    # base_url='http://192.168.100.70:11434/v1/',
    base_url="http://192.168.100.65:8080",
    api_key="ollama",
)

responses_result = client.responses.create(
    # model="google/gemma-3-12b-it",
    model="gpt-oss:120b",
    input="Write a short poem about the color blue",
)
print(responses_result.output_text)
