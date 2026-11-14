## Editing with Remotion in the sandbox

Remotion (open-source, React-based) is how you edit audio. It is pre-installed in your sandbox. One composition can combine as many operations on an episode as you need — cutting sections out, reordering, different gain per segment, fades at each join, layering a music bed.

What's in the sandbox:
- `/home/user/remotion-project` — the stock Remotion `template-empty` project with `@remotion/media` installed. Entry point `src/index.ts`, composition list in `src/Root.tsx`. `exec_sbx_command` starts in this folder.
- `/home/user/remotion-skills/skills/` — Remotion's official guides, as Markdown. Read the relevant ones with `sbx_read` before writing code rather than relying on memory: `remotion-markup/audio.md` (import, trim, volume, fades, speed), `remotion-markup/sequencing.md`, `remotion-markup/calculate-metadata.md` (set a composition's length from its audio), `remotion-markup/silence-detection.md`.
- `ffmpeg` and `ffprobe` — use `ffprobe` to get a file's duration and `ffmpeg` to measure loudness.

Workflow:
1. `sbx_upload` the current audio (a real `data/...` path) into `/home/user/remotion-project/public/`.
2. Write a composition with `sbx_write` (e.g. `src/Composition.tsx`) and register it in `src/Root.tsx`. Use `<Audio>` from `@remotion/media` with `staticFile("<file in public/>")`; `trimBefore` and `durationInFrames` are in frames, so convert seconds with the composition's `fps`. The composition's `durationInFrames` must cover the whole audio.
3. Render audio only: `npx remotion render src/index.ts <CompositionId> out/episode.mp3 --codec=mp3`. Pass a larger `timeout_s` to `exec_sbx_command` for long renders.
4. Check the render with `listen_audio(<sandbox path>, in_sandbox=True)` — no download needed. A render that finished without errors is not proof it sounds right. If it needs more work, change the composition and render again; every intermediate version stays in the sandbox.
5. Only when you're satisfied, `sbx_download` the finished episode into the book's `audio_contents` folder. The final file has to be local — the episode that gets published and the path you record in your rubric scores are local paths. Don't download drafts. The download is an identical copy of the render you just listened to, so there's no need to listen to it again locally.

Things that will bite you:
- An audio-only render still steps through every frame, so render time grows with `fps` × length. Use a low composition fps (10 is plenty for cuts and fades; the edit resolution is 1 frame = 100 ms) — a 30-minute episode is 18,000 frames at 10 fps but 180,000 at 100 fps.
- The sandbox is temporary and is deleted after a while. Download results as soon as they are rendered; don't plan on files still being there later.
- The same limit as everywhere else applies: at most two correction passes per dimension.
