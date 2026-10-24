import { createMp3Encoder } from "wasm-media-encoders";
import { parseWav } from "./wav.js";

export interface EncodedAudio {
  mp3: Buffer;
  samples: number;
  sampleRate: number;
  durationSeconds: number;
}

// Encodes a sequence of WAV clips into one mono MP3, inserting `gapSeconds` of silence between
// clips and after the last one.
export async function encodeClipsToMp3(
  wavs: Buffer[],
  gapSeconds: number,
  kbps: number
): Promise<EncodedAudio> {
  if (wavs.length === 0) throw new Error("No audio clips to encode");
  const clips = wavs.map(parseWav);
  const sampleRate = clips[0].sampleRate;
  for (const clip of clips) {
    if (clip.sampleRate !== sampleRate) {
      throw new Error(`Sample rate mismatch: ${clip.sampleRate} vs ${sampleRate}`);
    }
    if (clip.bitsPerSample !== 16) {
      throw new Error(`Unsupported bit depth ${clip.bitsPerSample} (expected 16-bit PCM)`);
    }
  }

  const encoder = await createMp3Encoder();
  encoder.configure({ sampleRate, channels: 1, bitrate: kbps as 64 });

  const gap = new Float32Array(Math.round(gapSeconds * sampleRate));
  const parts: Uint8Array[] = [];
  let samples = 0;

  const push = (chunk: Uint8Array) => {
    if (chunk.length > 0) parts.push(Uint8Array.from(chunk));
  };

  for (const clip of clips) {
    push(encoder.encode([toMonoFloat32(clip.pcm, clip.channels)]));
    samples += clip.pcm.length / (2 * clip.channels);
    push(encoder.encode([gap]));
    samples += gap.length;
  }
  push(encoder.finalize());

  return {
    mp3: stripToFirstFrame(Buffer.concat(parts)),
    samples,
    sampleRate,
    durationSeconds: samples / sampleRate,
  };
}

function toMonoFloat32(pcm: Buffer, channels: number): Float32Array {
  const frames = Math.floor(pcm.length / (2 * channels));
  const out = new Float32Array(frames);
  for (let i = 0; i < frames; i++) {
    let sum = 0;
    for (let c = 0; c < channels; c++) {
      sum += pcm.readInt16LE((i * channels + c) * 2);
    }
    out[i] = sum / channels / 32768;
  }
  return out;
}

function isFrameHeader(buf: Buffer, i: number): boolean {
  if (i + 4 > buf.length) return false;
  if (buf[i] !== 0xff || (buf[i + 1] & 0xe0) !== 0xe0) return false;
  const version = (buf[i + 1] >> 3) & 3;
  const layer = (buf[i + 1] >> 1) & 3;
  const bitrateIndex = buf[i + 2] >> 4;
  const sampleRateIndex = (buf[i + 2] >> 2) & 3;
  return version !== 1 && layer === 1 && bitrateIndex > 0 && bitrateIndex < 15 && sampleRateIndex !== 3;
}

// LAME prepends a tag block before the first audio frame; drop everything up to the first
// real frame so that independently encoded parts can be concatenated.
export function stripToFirstFrame(mp3: Buffer): Buffer {
  for (let i = 0; i < Math.min(mp3.length, 4096); i++) {
    if (isFrameHeader(mp3, i)) return i === 0 ? mp3 : mp3.subarray(i);
  }
  return mp3;
}

export function concatMp3Parts(parts: Buffer[]): Buffer {
  return Buffer.concat(parts.map(stripToFirstFrame));
}
