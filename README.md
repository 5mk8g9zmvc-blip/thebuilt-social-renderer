# TheBuilt five-scene social renderer

Copyright © 2026 TheBuilt. All rights reserved. No license is granted to use, copy, modify, distribute, or create derivative works from this repository.

This renderer replaces the exhausted Shotstack step while preserving the current quality standard:

- exactly five distinct images;
- exactly five matching ElevenLabs voiceovers;
- one text overlay per scene;
- the fifth scene is always the CTA;
- 1080×1920, 30 fps, H.264 video and AAC delivery audio;
- automatic voiceover timing, loudness normalisation, subtle image motion and final validation.

## Local render

```bash
python3 render_social.py example-manifest.json output.mp4
```

The command creates `output.mp4` and `output.report.json`. A failed asset, missing voiceover, incorrect scene count, invalid dimensions or missing audio causes a hard failure instead of a low-quality output.

ElevenLabs remains the voice generator. Its MP3 voiceover files are accepted as the five source tracks. FFmpeg encodes those existing voices as AAC only when packaging the final MP4 because AAC is the broadly compatible delivery codec for social video; it does not generate or replace the voice.

## Manifest

Each of the five scenes requires:

```json
{
  "role": "body",
  "image": "https://public.example/scene-01.png",
  "voiceover": "https://public.example/scene-01.mp3",
  "overlay": "One clear idea per scene",
  "duration": 4.5
}
```

`duration` is optional. The renderer automatically uses the longer of the requested duration or the voiceover duration plus 0.4 seconds.

## GitHub Actions handoff

The included workflow accepts a public `manifest_url` and produces a three-day GitHub Actions artifact containing the MP4 and validation report. n8n should:

1. generate and upload five images and five ElevenLabs voiceovers;
2. write the manifest to a public Dropbox URL;
3. trigger `render-social-video.yml` through the GitHub Actions API;
4. poll the run until completion;
5. download the artifact, upload the MP4 to Dropbox, and archive the package in Google Drive;
6. publish only when the report contains `"passed": true`.
