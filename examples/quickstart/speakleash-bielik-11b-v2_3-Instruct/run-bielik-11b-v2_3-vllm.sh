#!/bin/bash

export CUDA_VISIBLE_DEVICES=0

MODEL_PATH=speakleash/Bielik-11B-v2.3-Instruct

vllm serve \
	"${MODEL_PATH}" \
        --port 7000 \
        --host 0.0.0.0 \
        --quantization bitsandbytes \
        --load-format bitsandbytes \
        --max-model-len=56000 \
        --gpu-memory-utilization=0.80
