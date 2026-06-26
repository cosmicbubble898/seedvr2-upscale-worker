"""
RunPod serverless handler — SeedVR2 video upscaler.

Contract (matches the Local AI Aggregator app's /api/video/upscale):
  input:  { "video_base64": "<raw base64 mp4>", "scale": 2 | 4, "seed"?, "batch_size"? }
  output: { "video": "<base64 mp4>" }   (or { "error": "..." })

Runs a fixed ComfyUI workflow (seedvr2_upscale_api.json):
  VHS_LoadVideoPath -> SeedVR2 (DiT + VAE loaders) -> SeedVR2VideoUpscaler -> VHS_VideoCombine
The upscaler targets a shortest-edge resolution, so we ffprobe the input and set
target = round(short_edge * scale). Output fps + audio are carried from the source.
Adapted from wlsdml1114/generate_video's handler.
"""
import runpod
import os
import base64
import json
import uuid
import logging
import subprocess
import time
import urllib.request
import websocket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv("SERVER_ADDRESS", "127.0.0.1")
client_id = str(uuid.uuid4())


def save_base64_to_file(b64, temp_dir, filename):
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(temp_dir, filename))
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    logger.info(f"Saved input video -> {path} ({os.path.getsize(path)} bytes)")
    return path


def ffprobe_info(path):
    """Return (short_edge_px, fps) of the first video stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60,
        )
        s = json.loads(out.stdout)["streams"][0]
        w, h = int(s["width"]), int(s["height"])
        num, den = s["r_frame_rate"].split("/")
        fps = (float(num) / float(den)) if float(den) else 24.0
        return min(w, h), round(fps, 3)
    except Exception as e:
        logger.warning(f"ffprobe failed ({e}); defaulting short=720 fps=24")
        return 720, 24.0


def queue_prompt(prompt):
    data = json.dumps({"prompt": prompt, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(f"http://{server_address}:8188/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_history(prompt_id):
    with urllib.request.urlopen(f"http://{server_address}:8188/history/{prompt_id}") as r:
        return json.loads(r.read())


def get_output_video(ws, prompt):
    prompt_id = queue_prompt(prompt)["prompt_id"]
    while True:
        out = ws.recv()
        if isinstance(out, str):
            m = json.loads(out)
            if (m.get("type") == "executing"
                    and m["data"]["node"] is None
                    and m["data"]["prompt_id"] == prompt_id):
                break
    history = get_history(prompt_id)[prompt_id]
    for node_id in history["outputs"]:
        node_output = history["outputs"][node_id]
        if "gifs" in node_output:
            for video in node_output["gifs"]:
                with open(video["fullpath"], "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
    return None


def wait_for_comfy():
    for i in range(300):
        try:
            urllib.request.urlopen(f"http://{server_address}:8188/", timeout=5)
            logger.info(f"ComfyUI is ready (attempt {i + 1})")
            return
        except Exception:
            time.sleep(1)
    raise Exception("ComfyUI did not become ready in time")


def handler(job):
    job_input = job.get("input", {})
    task_id = f"task_{uuid.uuid4()}"

    if "video_base64" not in job_input:
        return {"error": "video_base64 is required"}
    video_path = save_base64_to_file(job_input["video_base64"], task_id, "input.mp4")

    try:
        scale = int(job_input.get("scale", 2))
    except Exception:
        scale = 2
    if scale not in (2, 4):
        scale = 2

    short_edge, fps = ffprobe_info(video_path)
    target_resolution = max(16, int(round(short_edge * scale / 2)) * 2)
    logger.info(f"short_edge={short_edge} fps={fps} scale={scale} -> resolution={target_resolution}")

    with open("/seedvr2_upscale_api.json", "r") as f:
        prompt = json.load(f)

    prompt["1"]["inputs"]["video"] = video_path
    prompt["4"]["inputs"]["resolution"] = target_resolution
    if "seed" in job_input:
        prompt["4"]["inputs"]["seed"] = int(job_input["seed"])
    if "batch_size" in job_input:
        prompt["4"]["inputs"]["batch_size"] = int(job_input["batch_size"])
    prompt["5"]["inputs"]["frame_rate"] = fps

    wait_for_comfy()
    ws = websocket.WebSocket()
    for attempt in range(36):
        try:
            ws.connect(f"ws://{server_address}:8188/ws?clientId={client_id}")
            logger.info(f"WebSocket connected (attempt {attempt + 1})")
            break
        except Exception as e:
            if attempt == 35:
                raise Exception(f"WebSocket connect failed: {e}")
            time.sleep(5)

    video_b64 = get_output_video(ws, prompt)
    ws.close()

    if video_b64:
        return {"video": video_b64}
    return {"error": "ComfyUI produced no video output"}


runpod.serverless.start({"handler": handler})
