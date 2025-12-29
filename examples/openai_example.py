"""
OpenAI SDK Integration Example

Demonstrates how to use the native OpenAI SDK with an LLM Router.
Change the base_url!
"""

import json
from openai import OpenAI, AsyncOpenAI

from constants import HOST, MODELS


class OpenAIExamples:
    """
    Helper class that groups all OpenAI‑Router example calls.
    Usage:
        examples = OpenAIExamples()
        examples.basic_example()
    """

    def __init__(self, host: str = HOST):
        # Create a single client used by all example methods
        self.client = OpenAI(
            base_url=host,
            api_key="not-needed",  # Router may not require an API key
        )

    # ---------------------------
    # 1. Basic Example
    # ---------------------------
    def basic_example(self):
        """Basic example using the OpenAI SDK"""
        response = self.client.chat.completions.create(
            model=MODELS[0],
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {
                    "role": "user",
                    "content": "Explain what an LLM Router is in one sentence.",
                },
            ],
            temperature=0.7,
        )
        print("Response:", response.choices[0].message.content)
        print(f"Usage: {response.usage}")
        return response

    # ---------------------------
    # 2. Streaming Example
    # ---------------------------
    def streaming_example(self):
        """Example demonstrating streaming responses"""
        print("Streaming response:")
        stream = self.client.chat.completions.create(
            model=MODELS[0],
            messages=[
                {
                    "role": "user",
                    "content": "Write a short poem about containerization.",
                },
            ],
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                print(chunk.choices[0].delta.content, end="", flush=True)
        print("\n")

    # ---------------------------
    # 3. Function Calling Example
    # ---------------------------
    def function_calling_example(self):
        """
        Full function‑calling example with a workaround for Gemma's strict template.
        Instead of using the 'tool' role, we send the tool result as a 'user' message
        to avoid the 'Conversation roles must alternate' error.
        """
        print("\n--- Starting Function Calling Example (Gemma Fix) ---")

        # Define the tool
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Fetches current weather for a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City and country, e.g., Warsaw, PL",
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                            },
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        # Combine system prompt with the first user message (Gemma dislikes 'system')
        initial_prompt = (
            "You are a helpful weather assistant. "
            "If the user asks about weather, "
            "you must use the get_current_weather tool.\n\n"
            "What is the weather in Warsaw?"
        )
        messages = [{"role": "user", "content": initial_prompt}]

        # STEP 1: Force the model to use the tool
        print("1. Sending request to the model...")
        response = self.client.chat.completions.create(
            model=MODELS[0],
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": "get_current_weather"},
            },
        )
        msg = response.choices[0].message
        print(f"   Received tool call: {msg.tool_calls}")

        # STEP 2: Handle the tool call
        if msg.tool_calls:
            messages.append(msg)
            for tool_call in msg.tool_calls:
                if tool_call.function.name == "get_current_weather":
                    args = json.loads(tool_call.function.arguments)
                    location = args.get("location", "Unknown")
                    print(f"2. Executing mock function for location: {location}")

                    # Mock result
                    weather_data = {
                        "location": location,
                        "temperature": 22,
                        "unit": "celsius",
                        "description": "Sunny, light wind",
                    }

                    # GEMMA FIX: send result as a user message
                    tool_result_message = {
                        "role": "user",
                        "content": (
                            f"Here is the result from get_current_weather: "
                            f"{json.dumps(weather_data)}. Please answer "
                            f"my original question based on this."
                        ),
                    }
                    messages.append(tool_result_message)

            # STEP 3: Send the results back to the model
            print("3. Sending function results back to the model...")
            final_response = self.client.chat.completions.create(
                model=MODELS[0],
                messages=messages,
                # No tools or tool_choice – we just want a textual answer now
            )
            final_content = final_response.choices[0].message.content
            print("\n=== FINAL MODEL RESPONSE ===")
            print(final_content)
            return final_response
        else:
            print("Error: Model did not invoke the function despite the request.")
            return response

    # ---------------------------
    # 4. Multi‑Message Conversation
    # ---------------------------
    def multi_message_conversation(self):
        """Example of a multi‑step conversation"""
        messages = [
            {
                "role": "system",
                "content": "You are an expert on distributed systems.",
            },
            {"role": "user", "content": "What is load balancing?"},
        ]

        # First response
        response = self.client.chat.completions.create(
            model=MODELS[0],
            messages=messages,
        )
        assistant_message = response.choices[0].message.content
        print("Assistant:", assistant_message)

        # Continue the conversation
        messages.append({"role": "assistant", "content": assistant_message})
        messages.append({"role": "user", "content": "Give a practical example."})

        # Second response
        response = self.client.chat.completions.create(
            model=MODELS[0],
            messages=messages,
        )
        print("Assistant:", response.choices[0].message.content)
        return response

    # ---------------------------
    # 5. Multi‑Model Example
    # ---------------------------
    def multi_model_example(self):
        """Example showing how to query multiple models via the router"""
        question = "Write a Python function to sort a list."
        for model in MODELS:
            print(f"\n{model}:")
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": question}],
                )
                print(response.choices[0].message.content)
            except Exception as e:
                print(f"  Error: {e}")

    # ---------------------------
    # 6. With Parameters Example
    # ---------------------------
    def with_parameters_example(self):
        """Example using custom generation parameters"""
        response = self.client.chat.completions.create(
            model=MODELS[0],
            messages=[
                {"role": "user", "content": "List three programming languages."},
            ],
            temperature=0.3,  # Low temperature = more deterministic output
            max_tokens=100,
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.5,
        )
        print("Response with custom parameters:")
        print(response.choices[0].message.content)
        return response

    # ---------------------------
    # 7. Async Example
    # ---------------------------
    def async_example(self):
        """Example using the asynchronous OpenAI client"""

        async def async_chat():
            async_client = AsyncOpenAI(
                base_url=HOST,
                api_key="not-needed",
            )
            response = await async_client.chat.completions.create(
                model=MODELS[0],
                messages=[
                    {"role": "user", "content": "What is asyncio?"},
                ],
            )
            print("Async response:", response.choices[0].message.content)
            return response

        import asyncio

        return asyncio.run(async_chat())

    # ---------------------------
    # 8. Batch Requests Example
    # ---------------------------
    def batch_requests_example(self):
        """Example sending multiple requests in a loop"""
        questions = [
            "What is Docker?",
            "What is Kubernetes?",
            "What is CI/CD?",
        ]
        print("Batch requests:")
        for i, question in enumerate(questions, 1):
            try:
                response = self.client.chat.completions.create(
                    model=MODELS[0],
                    messages=[{"role": "user", "content": question}],
                )
                print(f"{i}. {response.choices[0].message.content}")
            except Exception as e:
                print(f"Connection error: {e}")

    # ---------------------------
    # 9. Error Handling Example
    # ---------------------------
    def error_handling_example(self):
        """Example demonstrating error handling"""
        try:
            self.client.chat.completions.create(
                model="nonexistent-model",
                messages=[{"role": "user", "content": "Test"}],
            )
        except Exception as e:
            print(f"Error caught: {type(e).__name__}: {e}")

    # ---------------------------
    # 10. List Models Example
    # ---------------------------
    def list_models_example(self):
        """Example listing available models via the router"""
        try:
            models = self.client.models.list()
            print("Available models:")
            for model in models.data:
                print(f"  - {model.id}")
        except Exception as e:
            print(f"Could not list models: {e}")
            print("The router may not implement the /models endpoint")


if __name__ == "__main__":
    print("=" * 80)
    print("OpenAI SDK + LLM Router Integration Examples")
    print("=" * 80)

    examples = OpenAIExamples()

    print("\n1. Basic Example")
    print("-" * 80)
    examples.basic_example()

    print("\n2. Streaming Example")
    print("-" * 80)
    examples.streaming_example()

    print("\n3. Function Calling Example")
    print("-" * 80)
    examples.function_calling_example()

    print("\n4. Multi‑Message Conversation")
    print("-" * 80)
    examples.multi_message_conversation()

    print("\n5. Multi‑Model Example")
    print("-" * 80)
    examples.multi_model_example()

    print("\n6. Custom Parameters Example")
    print("-" * 80)
    examples.with_parameters_example()

    print("\n7. Async Example")
    print("-" * 80)
    examples.async_example()

    print("\n8. Batch Requests Example")
    print("-" * 80)
    examples.batch_requests_example()

    print("\n9. Error Handling Example")
    print("-" * 80)
    examples.error_handling_example()

    print("\n10. List Models Example")
    print("-" * 80)
    examples.list_models_example()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)
