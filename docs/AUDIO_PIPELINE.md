# ClayFarm local Text-to-Sound

ClayFarm now has an audio job contract for local text-to-audio runtimes. The
adapter runs offline on the worker and emits a WAV master plus review artifacts.
The contract is available to the local control queue and authenticated CLI.
The production PostgreSQL bridge still has a 3D-only task capability schema;
audio is not reported as centrally integrated until that schema and its worker
claim/finish path are migrated and tested together.

## Tracks and request contracts

BGM and SFX are separate request types. A BGM request must identify exactly
one track:

```json
{
  "track_id": "lobby",
  "prompt": "bright open welcoming melody with a stable cadence",
  "duration_seconds": 30,
  "bpm": 112,
  "loop_required": true,
  "seed": 101
}
```

The allowed BGM tracks are `lobby`, `preparation`, `combat`, and `result`.
They may share a palette and world tone, but they are not one generated track:

* `lobby` is open and inviting with a stable cadence.
* `preparation` is slower and harmonically tense with a repeating ostinato.
* `combat` emphasizes aggressive rhythm and low percussion.
* `result` is a short victory/defeat sting and normally does not loop.

SFX uses an event contract and variation count instead:

```json
{
  "event_id": "SwordHit",
  "prompt": "short metallic sword impact with a clay snap",
  "duration_seconds": 0.45,
  "variation_count": 4,
  "seed": 7
}
```

Model settings such as sampler, dimensions, and batch size remain profile
locked. Unknown fields are rejected at the API boundary.

The current single-WAV artifact contract executes one SFX variation per job;
requests with `variation_count` greater than one fail explicitly rather than
silently dropping the requested variations. A future bundle contract can add
multi-variation export without changing the BGM/SFX request boundary.

## Local execution

The first model profile is Stable Audio 3 Small-Music/SFX. The registry contains
CPU, CUDA, and MLX candidates, while the executable adapter is currently wired
only for the Python CPU profile. CUDA and MLX entries stay blocked until their
native runtime, pinned model files, and target-device measurements are
available. No hosted API or procedural fallback is used.

Install and verify a signed, pinned model release before generation:

```sh
clayfarm models sync --profile sa3-small-music-cpu \
  --recipe ./stable-audio-small-music-release.json \
  --accept-license --allow-download
clayfarm models verify sa3-small-music-cpu --spec examples/bgm-lobby.json
clayfarm models generate sa3-small-music-cpu \
  --spec examples/bgm-lobby.json --out ./audio/lobby
```

The release must identify a full model commit, every model-file SHA-256, a
hashed dependency lock, and a reviewed license. The model directory is kept
offline after sync. If `stable_audio_3`, PyTorch, torchaudio, or the local
snapshot is missing, verification fails with a sanitized error and the profile
cannot be advertised as ready.

## Post-processing and review

The generated tensor is written as 44.1 kHz mono/stereo WAV, then normalized to
a PCM 16-bit Unity master at `audio/<job>/asset.wav`. ClayFarm also writes:

* `waveform.json` — downsampled peak windows for a lightweight preview.
* `spectrogram.svg` — deterministic review preview, not a perceptual score.
* `audio-report.json` — sample rate, duration, RMS/peak, clipping count,
  trimmed silence, and loop seam metric.

`loop_seam_review_required` is raised when a requested loop has a large first /
last-frame discontinuity. A person must listen to the result and approve the
master before exporting it to Unity. Machine checks and a verified neural run
do not constitute musical or game-audio approval.

## Unity export

Only the approved `asset.wav` should be converted to OGG and added to the
existing BettingRoyal `SoundManager`/`AudioMixer` flow. Keep Lobby and
Preparation as separate clips and mixer entries. The ClayFarm API accepts audio
artifacts for both `sfx` and `music` profiles; image and UI artifact contracts
remain unchanged.

The Stable Audio 3 model and its Gemma text-conditioning component have their
own license terms. Review those terms and the exact dependency lock before any
commercial game release. ACE-Step 1.5 remains a BGM candidate for a later
bake-off; it is not part of the current ready set.
