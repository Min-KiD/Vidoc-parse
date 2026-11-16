"""Stage 2 and 3 (GPU): MinerU2.5-Pro, local engine, standard tier, on every image of a folder, several pages at once.

usage: mineru_dir.py <pages dir> <out dir> [--crops <crop pages dir> <crop out dir> <ready file>] [--jobs N]
  -> <out dir>/pNN.{raw.json,md}, then <out dir>/.done
  With --crops the same process (the model stays loaded) waits for <ready file>, written once the crops of stage 3
  are cut, and reads every image of <crop pages dir> into <crop out dir>.
--jobs: pages in flight at once (default 1). More is faster (VIC: 72 pages in 124 s at 8, against about 6 min at 1)
  but table cells then change from run to run: at 8, one run of VIC lost the item numbers of two labels on p10.
"""
import asyncio, os, pathlib, sys, time

for k in ("MINERU_API_URL", "MINERU_API_KEY", "MINERU_MODEL_VLM_API_KEY"):
    assert not os.environ.get(k), f"{k} set: remote mode is forbidden"


async def read_dir(pages, out, jobs):
    from mineru.parser import parse_async
    out.mkdir(parents=True, exist_ok=True)
    todo = [img for img in sorted(pages.glob("p*.png")) if not (out / f"{img.stem}.md").exists()]
    gate = asyncio.Semaphore(jobs)

    async def one(img):
        async with gate:
            t = time.time()
            res = await parse_async(str(img), tier="standard")
            (out / f"{img.stem}.raw.json").write_text(res.to_json())
            (out / f"{img.stem}.md").write_text(res.markdown())
            print(img.stem, f"{time.time() - t:.1f}s", flush=True)

    t = time.time()
    await asyncio.gather(*(one(img) for img in todo))
    print(f"{pages}: {len(todo)} pages in {time.time() - t:.1f}s", flush=True)


async def main(argv):
    jobs = 1
    if "--jobs" in argv:
        i = argv.index("--jobs"); jobs = int(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
    crops = None
    if "--crops" in argv:
        i = argv.index("--crops"); crops = [pathlib.Path(a) for a in argv[i + 1:i + 4]]; argv = argv[:i]
    pages, out = map(pathlib.Path, argv[:2])
    await read_dir(pages, out, jobs)
    (out / ".done").touch()
    if crops:
        crop_pages, crop_out, ready = crops
        while not ready.exists():
            await asyncio.sleep(2)
        if crop_pages.exists():
            await read_dir(crop_pages, crop_out, jobs)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
