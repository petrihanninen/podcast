export interface WavInfo {
  sampleRate: number;
  channels: number;
  bitsPerSample: number;
  pcm: Buffer;
}

export function parseWav(buf: Buffer): WavInfo {
  if (buf.length < 12 || buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error("Not a RIFF/WAVE file");
  }
  let offset = 12;
  let fmt: { sampleRate: number; channels: number; bitsPerSample: number } | null = null;
  while (offset + 8 <= buf.length) {
    const id = buf.toString("ascii", offset, offset + 4);
    const size = buf.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (id === "fmt ") {
      const format = buf.readUInt16LE(body);
      if (format !== 1 && format !== 0xfffe) {
        throw new Error(`Unsupported WAV format tag ${format} (expected PCM)`);
      }
      fmt = {
        channels: buf.readUInt16LE(body + 2),
        sampleRate: buf.readUInt32LE(body + 4),
        bitsPerSample: buf.readUInt16LE(body + 14),
      };
    } else if (id === "data") {
      if (!fmt) throw new Error("WAV data chunk before fmt chunk");
      const end = Math.min(buf.length, body + size);
      return { ...fmt, pcm: buf.subarray(body, end) };
    }
    offset = body + size + (size % 2);
  }
  throw new Error("WAV file has no data chunk");
}

export function buildWav(
  pcm: Buffer,
  sampleRate: number,
  channels: number,
  bitsPerSample: number
): Buffer {
  const header = Buffer.alloc(44);
  const blockAlign = (channels * bitsPerSample) / 8;
  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8, "ascii");
  header.write("fmt ", 12, "ascii");
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * blockAlign, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

export function wavDurationSeconds(info: WavInfo): number {
  return info.pcm.length / ((info.sampleRate * info.channels * info.bitsPerSample) / 8);
}

export function concatWavs(
  wavs: Buffer[],
  gapSeconds: number
): { wav: Buffer; durationSeconds: number } {
  if (wavs.length === 0) throw new Error("No WAV segments to concatenate");
  const parts = wavs.map(parseWav);
  const { sampleRate, channels, bitsPerSample } = parts[0];
  for (const p of parts) {
    if (p.sampleRate !== sampleRate || p.channels !== channels || p.bitsPerSample !== bitsPerSample) {
      throw new Error(
        `WAV format mismatch: ${p.sampleRate}Hz/${p.channels}ch/${p.bitsPerSample}bit vs ${sampleRate}Hz/${channels}ch/${bitsPerSample}bit`
      );
    }
  }
  const blockAlign = (channels * bitsPerSample) / 8;
  const gapBytes = Math.round(gapSeconds * sampleRate) * blockAlign;
  const gap = Buffer.alloc(gapBytes);
  const chunks: Buffer[] = [];
  parts.forEach((p, i) => {
    if (i > 0) chunks.push(gap);
    chunks.push(p.pcm);
  });
  const pcm = Buffer.concat(chunks);
  return {
    wav: buildWav(pcm, sampleRate, channels, bitsPerSample),
    durationSeconds: pcm.length / (sampleRate * blockAlign),
  };
}
