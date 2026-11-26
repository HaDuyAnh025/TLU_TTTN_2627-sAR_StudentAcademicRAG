"""Mở giao diện duyệt câu hỏi đánh giá (xem docs/HUONG_DAN_DUYET.md, mục "Duyệt bộ câu hỏi đánh giá retrieval").

  python scripts/review_testset.py --reviewer "Tên bạn"
  python scripts/review_testset.py --reviewer "Tên bạn" --shard 2/3 --file data/eval/questions.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.evaluation import testset_ui as U  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", default="", help="tên người duyệt (ghi vào review.reviewer)")
    ap.add_argument("--shard", default="1/1", help="K/N: hàng đợi riêng của người thứ K trong N người (chia theo thứ tự id)")
    ap.add_argument("--file", help="questions.jsonl (mặc định data/eval/questions.jsonl)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    k, n = (int(x) for x in a.shard.split("/"))
    if not (1 <= k <= n):
        raise SystemExit("--shard phải dạng K/N với 1 <= K <= N")
    store = U.default_store(a.reviewer, (k, n), Path(a.file) if a.file else None)
    U.serve(store, a.port, not a.no_browser)


if __name__ == "__main__":
    main()
