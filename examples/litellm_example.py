"""
LiteLLM Integration Example

Demonstrates how to use LiteLLM as a proxy for an LLM Router.
LiteLLM provides a unified API for 100+ LLM providers.
"""

import asyncio
import litellm
from litellm import completion, acompletion, Router, Cache

from constants import HOST, MODELS


class LiteLLMExamples:
    """
    Helper class that groups all LiteLLM‑Router example calls.
    Usage:
        examples = LiteLLMExamples()
        examples.basic_example()
    """

    def __init__(self, host: str = HOST):
        # Base URL of the router (e.g. http://localhost:5555/api/v1)
        self.base_url = host
        # Models list – first element is the default Gemma model
        self.models = MODELS

    # ------------ 1. Basic Example ------------
    def basic_example(self):
        """Basic example using LiteLLM"""
        response = completion(
            model=f"openai/{self.models[0]}",  # prefix required by LiteLLM
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": "Explain what an LLM Router is."},
            ],
            api_base=self.base_url,
            api_key="not-needed",
        )
        print("Response:", response.choices[0].message.content)
        print(f"Usage: {response.usage}")
        return response

    # ------------ 2. Streaming Example ------------
    def streaming_example(self):
        """Streaming response example"""
        print("Streaming response:")
        response = completion(
            model=f"openai/{self.models[0]}",
            messages=[
                {
                    "role": "user",
                    "content": "Write a short poem about load balancing.",
                }
            ],
            api_base=self.base_url,
            api_key="not-needed",
            stream=True,
        )
        for chunk in response:
            if (
                hasattr(chunk.choices[0].delta, "content")
                and chunk.choices[0].delta.content
            ):
                print(chunk.choices[0].delta.content, end="", flush=True)
        print("\n")

    # ------------ 3. With Retries Example ------------
    def with_retries_example(self):
        """Automatic retry on failures (LiteLLM feature)"""
        response = completion(
            model=f"openai/{self.models[0]}",
            messages=[{"role": "user", "content": "What is failover?"}],
            api_base=self.base_url,
            api_key="not-needed",
            num_retries=3,
            timeout=30,
        )
        print("Response with retries:", response.choices[0].message.content)
        return response

    # ------------ 4. Fallback Example ------------
    def fallback_example(self):
        """Fallback between multiple models (LiteLLM feature)"""
        fallback_models = [
            f"openai/{self.models[0]}",
            f"openai/{self.models[1]}",
        ]
        for model in fallback_models:
            try:
                response = completion(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": "List three advantages of microservices.",
                        }
                    ],
                    api_base=self.base_url,
                    api_key="not-needed",
                    timeout=10,
                )
                print(f"Success with {model}:")
                print(response.choices[0].message.content)
                break
            except Exception as e:
                print(f"Failed with {model}: {e}")
                continue

    # ------------ 5. Async Example ------------
    def async_example(self):
        """Asynchronous API example"""

        async def async_chat():
            response = await acompletion(
                model=f"openai/{self.models[0]}",
                messages=[{"role": "user", "content": "What is async programming?"}],
                api_base=self.base_url,
                api_key="not-needed",
            )
            print("Async response:", response.choices[0].message.content)
            return response

        return asyncio.run(async_chat())

    # # ------------ 6. Cost Tracking Example ------------
    # def cost_tracking_example(self):
    #     """Cost tracking (LiteLLM feature)"""
    #     # Optional: integrate with Langfuse or another analytics provider
    #     litellm.success_callback = ["langfuse"]
    #
    #     response = completion(
    #         model=f"openai/{self.models[0]}",
    #         messages=[{"role": "user", "content": "Brief answer about cost optimization."}],
    #         api_base=self.base_url,
    #         api_key="not-needed",
    #     )
    #     print("Response:", response.choices[0].message.content)
    #     if hasattr(response, "_hidden_params"):
    #         print("Cost info:", response._hidden_params.get("response_cost", "N/A"))
    #     return response

    # ------------ 7. Batch Completion Example ------------
    def batch_completion_example(self):
        """Batch completion example"""
        messages_list = [
            [{"role": "user", "content": "What is a REST API?"}],
            [{"role": "user", "content": "What is GraphQL?"}],
            [{"role": "user", "content": "What is gRPC?"}],
        ]
        print("Batch completion:")
        for i, msgs in enumerate(messages_list, 1):
            response = completion(
                model=f"openai/{self.models[0]}",
                messages=msgs,
                api_base=self.base_url,
                api_key="not-needed",
                max_tokens=50,
            )
            print(f"{i}. {response.choices[0].message.content}\n")
        return None

    # ------------ 8. Custom Parameters Example ------------
    def custom_parameters_example(self):
        """Custom generation parameters"""
        response = completion(
            model=f"openai/{self.models[0]}",
            messages=[
                {"role": "user", "content": "List three programming languages."}
            ],
            api_base=self.base_url,
            api_key="not-needed",
            temperature=0.2,
            max_tokens=100,
            top_p=0.9,
            frequency_penalty=0.3,
            presence_penalty=0.3,
        )
        print("Response with custom params:")
        print(response.choices[0].message.content)
        return response

    # ------------ 9. Caching Example ------------
    def caching_example(self):
        """In‑memory caching (LiteLLM feature)"""
        litellm.cache = Cache()  # enable cache

        print("First call (not cached):")
        response1 = completion(
            model=f"openai/{self.models[0]}",
            messages=[{"role": "user", "content": "What is caching?"}],
            api_base=self.base_url,
            api_key="not-needed",
            caching=True,
        )
        print(response1.choices[0].message.content)

        print("\nSecond call (should be cached):")
        response2 = completion(
            model=f"openai/{self.models[0]}",
            messages=[{"role": "user", "content": "What is caching?"}],
            api_base=self.base_url,
            api_key="not-needed",
            caching=True,
        )
        print(response2.choices[0].message.content)

    # ------------ 10. Router Config Example ------------
    def router_config_example(self):
        """Custom LiteLLM router configuration together with the external LLM Router"""
        model_list = [
            {
                "model_name": "gemma",
                "litellm_params": {
                    "model": f"openai/{self.models[0]}",
                    "api_base": self.base_url,
                    "api_key": "not-needed",
                },
            },
            {
                "model_name": "qwen",
                "litellm_params": {
                    "model": "openai/qwen3-coder:30b",
                    "api_base": self.base_url,
                    "api_key": "not-needed",
                },
            },
        ]
        router = Router(model_list=model_list)

        response = router.completion(
            model="gemma",
            messages=[{"role": "user", "content": "What is routing?"}],
        )
        print("Router response:", response.choices[0].message.content)
        return response

    # ------------ 11. Error Handling Example ------------
    def error_handling_example(self):
        """Demonstrates error handling for LiteLLM calls"""
        try:
            response = completion(
                model="openai/nonexistent-model",
                messages=[{"role": "user", "content": "Test"}],
                api_base=self.base_url,
                api_key="not-needed",
            )
        except litellm.exceptions.BadRequestError as e:
            print(f"Bad request: {e}")
        except litellm.exceptions.Timeout as e:
            print(f"Timeout: {e}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("=" * 80)
    print("LiteLLM + LLM Router Integration Examples")
    print("=" * 80)

    examples = LiteLLMExamples()

    print("\n1. Basic Example")
    print("-" * 80)
    examples.basic_example()

    print("\n2. Streaming Example")
    print("-" * 80)
    examples.streaming_example()

    print("\n3. With Retries Example")
    print("-" * 80)
    examples.with_retries_example()

    print("\n4. Fallback Example")
    print("-" * 80)
    examples.fallback_example()

    print("\n5. Async Example")
    print("-" * 80)
    examples.async_example()

    # print("\n6. Cost Tracking Example")
    # print("-" * 80)
    # examples.cost_tracking_example()

    print("\n7. Batch Completion Example")
    print("-" * 80)
    examples.batch_completion_example()

    print("\n8. Custom Parameters Example")
    print("-" * 80)
    examples.custom_parameters_example()

    print("\n9. Caching Example")
    print("-" * 80)
    examples.caching_example()

    print("\n10. Router Config Example")
    print("-" * 80)
    examples.router_config_example()

    print("\n11. Error Handling Example")
    print("-" * 80)
    examples.error_handling_example()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)
