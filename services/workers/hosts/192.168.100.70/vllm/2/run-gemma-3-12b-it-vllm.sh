#!/bin/bash

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=2

MODEL_PATH=google/gemma-3-12b-it

vllm serve \
        "${MODEL_PATH}" \
        --port 7002 \
        --host 0.0.0.0 \
        --quantization bitsandbytes \
        --load-format bitsandbytes \
        --max-model-len=56000 \
        --max_num_seqs=8 \
        --gpu-memory-utilization=0.90
