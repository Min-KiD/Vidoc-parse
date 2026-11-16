"""Stage 2 and 3 (GPU): MinerU2.5-Pro, local engine, standard tier, on every image of a folder.

usage: mineru_dir.py <pages dir> <out dir>  -> <out dir>/pNN.{raw.json,md}
"""
import os, pathlib, sys, time

for k in ("MINERU_API_URL", "MINERU_API_KEY", "MINERU_MODEL_VLM_API_KEY"):
    assert not os.environ.get(k), f"{k} set: remote mode is forbidden"


def main(pages, out):
    from mineru.parser import parse
    out.mkdir(parents=True, exist_ok=True)
    for img in sorted(pages.glob("p*.png")):
        if (out / f"{img.stem}.md").exists():
            continue
        t = time.time()
        res = parse(str(img), tier="standard")
        (out / f"{img.stem}.raw.json").write_text(res.to_json())
        (out / f"{img.stem}.md").write_text(res.markdown())
        print(img.stem, f"{time.time() - t:.1f}s", flush=True)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
