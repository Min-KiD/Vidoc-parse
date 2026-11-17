"""Stage 2 and 3 (GPU): MinerU2.5-Pro, local engine, standard tier, on every image of a folder.

usage: mineru_dir.py <pages dir> <out dir> [--until <file>] [--crops <crop pages dir> <crop out dir> <ready file>]
                     [--jobs N]
  -> <out dir>/pNN.{raw.json,md}, then <out dir>/.done. pNN.md is written last and under its name only when complete,
  so a page whose .md exists is finished.
  --until: the page images are still being written; read each one as it appears until <file> exists.
  --crops: the same process (the model stays loaded) then waits for <ready file>, written once the crops of stage 3
  are cut, and reads every image of <crop pages dir> into <crop out dir>.
--jobs: pages in flight at once (default 1). More is faster (VIC: 72 pages in 124 s at 8, against about 6 min at 1)
  but table cells then change from run to run: at 8, one run of VIC lost the item numbers of two labels on p10.
The model is loaded by the first page read: a run with nothing left to read does not load it.
"""
import asyncio, os, pathlib, sys, time

for k in ("MINERU_API_URL", "MINERU_API_KEY", "MINERU_MODEL_VLM_API_KEY"):
    assert not os.environ.get(k), f"{k} set: remote mode is forbidden"


async def read_dir(pages, out, jobs, until=None):
    out.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(jobs)

    async def one(img):
        from mineru.parser import parse_async
        async with gate:
            t = time.time()
            res = await parse_async(str(img), tier="standard")
            (out / f"{img.stem}.raw.json").write_text(res.to_json())
            tmp = out / f".tmp_{img.stem}.md"
            tmp.write_text(res.markdown())
            tmp.rename(out / f"{img.stem}.md")
            print(img.stem, f"{time.time() - t:.1f}s", flush=True)

    t, seen, tasks = time.time(), set(), []
    while True:
        last = until is None or until.exists()  # looked at before the images, so none is missed
        for img in sorted(pages.glob("p*.png")):
            if img.name not in seen and not (out / f"{img.stem}.md").exists():
                seen.add(img.name)
                tasks.append(asyncio.create_task(one(img)))
        if last:
            break
        await asyncio.sleep(0.5)
    await asyncio.gather(*tasks)
    print(f"{pages}: {len(tasks)} images in {time.time() - t:.1f}s", flush=True)


def option(argv, name, n):
    if name not in argv:
        return argv, None
    i = argv.index(name)
    return argv[:i] + argv[i + 1 + n:], argv[i + 1:i + 1 + n]


async def main(argv):
    argv, jobs = option(argv, "--jobs", 1)
    argv, until = option(argv, "--until", 1)
    argv, crops = option(argv, "--crops", 3)
    pages, out = map(pathlib.Path, argv[:2])
    jobs = int(jobs[0]) if jobs else 1
    await read_dir(pages, out, jobs, pathlib.Path(until[0]) if until else None)
    (out / ".done").touch()
    if crops:
        crop_pages, crop_out, ready = map(pathlib.Path, crops)
        while not ready.exists():
            await asyncio.sleep(1)
        if crop_pages.exists():
            await read_dir(crop_pages, crop_out, jobs)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
