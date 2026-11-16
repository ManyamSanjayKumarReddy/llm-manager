# vLLM 0.10.1 that aborts running requests inside /sleep (what vLLM >= 0.17 does), for servers whose
# NVIDIA driver is too old for the CUDA 12.9 images. Build on the GPU server:
#   docker build -t vllm-openai:v0.10.1-abortsleep scripts/vllm-abort-sleep
# then run it exactly like vllm/vllm-openai:v0.10.1 (same flags, only the image name changes).
ARG BASE=vllm/vllm-openai:v0.10.1
FROM ${BASE}
COPY patch.py /tmp/patch.py
RUN python3 /tmp/patch.py && rm /tmp/patch.py
