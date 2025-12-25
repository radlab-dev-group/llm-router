#!/bin/bash

export LLM_ROUTER_LANGCHAIN_RAG_COLLECTION=${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION:-"sample_collection"}
export LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER=${LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER:-"/mnt/data2/llms/models/community/google/embeddinggemma-300m"}
export LLM_ROUTER_LANGCHAIN_RAG_DEVICE=${LLM_ROUTER_LANGCHAIN_RAG_DEVICE:-"cuda:2"}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE:-1024}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP:-100}
export LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR=${LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR:-"./workdir/plugins/utils/rag/langchain/${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION}"}

llm-router-rag-langchain index --path "../llm-router" --ext .py .md .txt .sh
llm-router-rag-langchain index --path "../llm-router-plugins" --ext .py .md .txt .sh
llm-router-rag-langchain index --path "../llm-router-services" --ext .py .md .txt .sh
llm-router-rag-langchain index --path "../llm-router-utils" --ext .py .md .txt .sh
llm-router-rag-langchain index --path "../llm-router-web" --ext .py .md .txt .sh
llm-router-rag-langchain index --path "../.github/pages/llmrouter.cloud/" --ext .html .js .md .txt .py
