"""Đóng gói dự án để gửi lên máy thuê: tạo ../sar_gpu_pack.zip (đường dẫn dùng '/', mở được trên Linux).

Chạy tại thư mục gốc sAR:  python deploy/pack.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT.parent / "sar_gpu_pack.zip"
INCLUDE = ["src", "scripts", "configs", "deploy", "data/raw/files", "data/raw/pages", "data/eval"]
SINGLE = ["data/raw/manifest.jsonl", "requirements.txt"]
SKIP_DIRS = {"__pycache__", ".venv"}


def main() -> None:
    if ZIP.exists():
        ZIP.unlink()
    n = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in SINGLE:
            z.write(ROOT / rel, rel)
            n += 1
        for rel in INCLUDE:
            for p in sorted((ROOT / rel).rglob("*")):
                if p.is_file() and not (SKIP_DIRS & set(p.parts)) and p.suffix != ".pyc":
                    arc = p.relative_to(ROOT).as_posix()
                    data = p.read_bytes()
                    if arc.endswith(".sh"):  # bỏ BOM và CRLF để bash chạy được
                        data = data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
                    z.writestr(arc, data)
                    n += 1
    print(f"{ZIP}  ({ZIP.stat().st_size / 1e6:.0f} MB, {n} file)")


if __name__ == "__main__":
    main()
