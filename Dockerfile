# SeedVR2 video-upscale serverless worker for RunPod.
# Reuses wlsdml1114's Blackwell base (proven on RTX PRO 6000 / 50-series) so CUDA +
# torch + sage-attention already match the GPU. We add a fresh ComfyUI + the video
# helper nodes + the SeedVR2 node. Weights are NOT baked (the 7B is ~16 GB and would
# blow RunPod's 30-min image-export limit) — the SeedVR2 node auto-downloads them to
# ComfyUI/models/SEEDVR2 on the first job (one-time, slow cold start).
FROM wlsdml1114/engui_genai-base_blackwell:1.1 as runtime

RUN pip install -U "huggingface_hub[hf_transfer]"
RUN pip install runpod websocket-client

WORKDIR /

RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd /ComfyUI && \
    pip install -r requirements.txt

# Video load/combine (mp4 in -> frames, frames + audio -> mp4 out)
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite && \
    cd ComfyUI-VideoHelperSuite && \
    pip install -r requirements.txt

# SeedVR2 video upscaler node (DiT + VAE loaders + the upscaler)
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler && \
    cd ComfyUI-SeedVR2_VideoUpscaler && \
    pip install -r requirements.txt

COPY . .
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
