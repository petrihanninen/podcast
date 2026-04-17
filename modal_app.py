"""Modal app for GPU-accelerated TTS using Chatterbox Turbo.

Deployed separately to Modal and called remotely via HTTP web endpoint.
The model is baked into the image at build time to avoid cold-start downloads.

Deploy: modal deploy modal_app.py
Test:   modal run modal_app.py
"""

import base64
import io
import logging
import os
import tempfile
import time

import modal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = modal.App("podcast-tts")

# CUDA image with all TTS dependencies
tts_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("chatterbox-tts>=0.1.7", "torchaudio", "pydub>=0.25")
)


def _download_model():
    """Download and cache the Chatterbox Turbo model at image build time."""
    import perth

    perth.PerthImplicitWatermarker = perth.DummyWatermarker

    from chatterbox.tts_turbo import ChatterboxTurboTTS

    # Download to default cache — gets baked into the image layer
    ChatterboxTurboTTS.from_pretrained(device="cpu")


# Bake model weights into the image so cold starts skip the download
tts_image = tts_image.run_function(
    _download_model, secrets=[modal.Secret.from_name("huggingface")]
)


@app.function(
    image=tts_image,
    gpu="T4",
    timeout=1800,
    secrets=[modal.Secret.from_name("huggingface")],
)
def generate_tts(
    segments: list[dict],
    host_a_name: str,
    voice_ref_a_bytes: bytes | None,
    voice_ref_b_bytes: bytes | None,
) -> dict:
    """Generate TTS audio for podcast segments on a T4 GPU.

    Args:
        segments: List of {"speaker": str, "text": str} dicts.
        host_a_name: Name of host A (to match segments to voice refs).
        voice_ref_a_bytes: WAV bytes for host A's voice reference, or None.
        voice_ref_b_bytes: WAV bytes for host B's voice reference, or None.

    Returns:
        {"wav_bytes": bytes, "metrics": dict}
    """
    import perth
    import torch
    import torchaudio as ta
    from pydub import AudioSegment

    # Swap watermarker before importing ChatterboxTurboTTS
    perth.PerthImplicitWatermarker = perth.DummyWatermarker

    from chatterbox.tts_turbo import ChatterboxTurboTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading Chatterbox Turbo model on %s...", device)
    model_start = time.monotonic()
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    sample_rate = model.sr
    model_load_time = time.monotonic() - model_start
    logger.info("Model loaded in %.1fs (sample rate: %d)", model_load_time, sample_rate)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write voice ref bytes to temp files if provided
        voice_ref_a_path = None
        voice_ref_b_path = None

        if voice_ref_a_bytes:
            voice_ref_a_path = os.path.join(tmpdir, "voice_ref_a.wav")
            with open(voice_ref_a_path, "wb") as f:
                f.write(voice_ref_a_bytes)
            logger.info("Wrote host A voice ref: %d bytes", len(voice_ref_a_bytes))

        if voice_ref_b_bytes:
            voice_ref_b_path = os.path.join(tmpdir, "voice_ref_b.wav")
            with open(voice_ref_b_path, "wb") as f:
                f.write(voice_ref_b_bytes)
            logger.info("Wrote host B voice ref: %d bytes", len(voice_ref_b_bytes))

        # Generate each segment
        segment_wavs = []
        segment_durations = []
        total_gen_start = time.monotonic()

        for i, segment in enumerate(segments):
            text = segment["text"]
            speaker = segment["speaker"]

            voice_ref = (
                voice_ref_a_path if speaker == host_a_name else voice_ref_b_path
            )

            logger.info(
                "Generating segment %d/%d (%s): %s...",
                i + 1,
                len(segments),
                speaker,
                text[:50],
            )

            kwargs = {"text": text}
            if voice_ref:
                kwargs["audio_prompt_path"] = voice_ref

            seg_start = time.monotonic()
            wav = model.generate(**kwargs)
            seg_duration = time.monotonic() - seg_start
            segment_durations.append(round(seg_duration, 2))
            segment_wavs.append(wav)

            logger.info("Segment %d generated in %.1fs", i + 1, seg_duration)

        total_gen_duration = time.monotonic() - total_gen_start

        # Concatenate all segments with 300ms silence
        logger.info("Concatenating %d segments...", len(segments))
        silence = AudioSegment.silent(duration=300, frame_rate=sample_rate)
        combined = AudioSegment.empty()

        for wav_tensor in segment_wavs:
            buf = io.BytesIO()
            ta.save(buf, wav_tensor, sample_rate, format="wav")
            buf.seek(0)
            segment_audio = AudioSegment.from_wav(buf)
            if len(combined) > 0:
                combined += silence
            combined += segment_audio

        # Export combined WAV to bytes
        output_buf = io.BytesIO()
        combined.export(output_buf, format="wav")
        wav_bytes = output_buf.getvalue()

    audio_duration = len(combined) / 1000
    avg_per_segment = (
        sum(segment_durations) / len(segment_durations) if segment_durations else 0
    )

    metrics = {
        "duration_seconds": round(total_gen_duration, 2),
        "model_load_seconds": round(model_load_time, 2),
        "segment_count": len(segments),
        "segments_generated": len(segment_durations),
        "audio_duration_seconds": round(audio_duration, 2),
        "avg_segment_seconds": round(avg_per_segment, 2),
        "realtime_factor": round(
            audio_duration / total_gen_duration if total_gen_duration > 0 else 0, 2
        ),
        "segment_durations": segment_durations,
        "device": device,
    }

    logger.info(
        "TTS complete: %.1fs audio, %.1fs generation (%.1fx realtime), device=%s",
        audio_duration,
        total_gen_duration,
        metrics["realtime_factor"],
        device,
    )

    return {"wav_bytes": wav_bytes, "metrics": metrics}


@app.function(
    image=tts_image,
    gpu="T4",
    timeout=1800,
    secrets=[modal.Secret.from_name("huggingface")],
)
@modal.fastapi_endpoint(method="POST")
def generate_tts_web(body: dict) -> dict:
    """HTTP web endpoint wrapper for generate_tts.

    Accepts JSON with base64-encoded voice ref bytes, returns JSON with
    base64-encoded WAV bytes. This allows non-Python clients (TypeScript)
    to call the TTS function over HTTP.

    Request body:
        {
            "segments": [...],
            "host_a_name": "Alex",
            "voice_ref_a_bytes": "<base64 string or null>",
            "voice_ref_b_bytes": "<base64 string or null>"
        }

    Response:
        {
            "wav_bytes": "<base64 string>",
            "metrics": {...}
        }
    """
    segments = body["segments"]
    host_a_name = body["host_a_name"]

    # Decode base64 voice refs
    voice_ref_a = body.get("voice_ref_a_bytes")
    voice_ref_b = body.get("voice_ref_b_bytes")
    voice_ref_a_bytes = base64.b64decode(voice_ref_a) if voice_ref_a else None
    voice_ref_b_bytes = base64.b64decode(voice_ref_b) if voice_ref_b else None

    # Call the actual TTS function
    result = generate_tts.local(
        segments=segments,
        host_a_name=host_a_name,
        voice_ref_a_bytes=voice_ref_a_bytes,
        voice_ref_b_bytes=voice_ref_b_bytes,
    )

    # Encode WAV bytes as base64 for JSON transport
    return {
        "wav_bytes": base64.b64encode(result["wav_bytes"]).decode("ascii"),
        "metrics": result["metrics"],
    }


@app.local_entrypoint()
def main():
    """Local test entrypoint: `modal run modal_app.py`."""
    test_segments = [
        {"text": "Hello, this is a test of the podcast TTS system.", "speaker": "Alex"},
        {"text": "And this is the second speaker responding.", "speaker": "Jordan"},
    ]

    logger.info("Testing Modal TTS function...")
    result = generate_tts.remote(
        segments=test_segments,
        host_a_name="Alex",
        voice_ref_a_bytes=None,
        voice_ref_b_bytes=None,
    )

    logger.info("Generated %d bytes of audio", len(result["wav_bytes"]))
    logger.info("Metrics: %s", result["metrics"])
