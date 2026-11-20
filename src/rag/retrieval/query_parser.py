"""Phân tích câu hỏi: khóa, bậc đào tạo, học kỳ, năm học, mã học phần. Câu hỏi nêu rõ thì ưu tiên hơn user_ctx."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag.retrieval import normalize as N

BAC_RULES = [  # (bậc, regex trên văn bản đã NFC + lower); thứ tự = ưu tiên
    ("sau_dai_hoc", re.compile(r"thạc\s*sĩ|cao\s*học|tiến\s*sĩ|nghiên\s*cứu\s*sinh|sau\s*đại\s*học|(?<!\w)ncs(?!\w)")),
    ("vua_lam_vua_hoc", re.compile(r"vừa\s*làm\s*vừa\s*học|(?<!\w)vlvh(?!\w)")),
    ("lien_thong", re.compile(r"liên\s*thông")),
]
MA_HP_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,4}\d{3}(?![A-Za-z0-9])")


@dataclass
class ParsedQuery:
    text: str
    khoa: int | list[int] | None = None   # 38 | [35, 36, 37] | None
    bac_dao_tao: str | None = None
    hoc_ky: str | None = None             # hk1 | hk2 | hk3 | hkphu | hkhe
    nam_hoc: str | None = None            # 2025_2026
    ma_hoc_phan: list[str] = field(default_factory=list)
    flags: dict = field(default_factory=dict)  # nguồn của khóa/bậc: "query" | "ctx"

    @property
    def khoa_list(self) -> list[int]:
        return [] if self.khoa is None else ([self.khoa] if isinstance(self.khoa, int) else list(self.khoa))


def _ctx_khoa(v) -> int | list[int] | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = [int(x) for x in v]
        return v[0] if len(v) == 1 else v
    return int(v)


def parse_query(text: str, user_ctx: dict | None = None) -> ParsedQuery:
    ctx = user_ctx or {}
    low = N.prep(text)
    flags: dict = {}

    ks = N.find_khoa(text)
    khoa: int | list[int] | None = None
    if ks:
        khoa, flags["khoa"] = (ks[0] if len(ks) == 1 else ks), "query"
    elif ctx.get("khoa") is not None:
        khoa, flags["khoa"] = _ctx_khoa(ctx["khoa"]), "ctx"

    bac = next((b for b, rx in BAC_RULES if rx.search(low)), None)
    if bac:
        flags["bac_dao_tao"] = "query"
    elif ctx.get("bac_dao_tao"):
        bac, flags["bac_dao_tao"] = ctx["bac_dao_tao"], "ctx"

    hk = N.find_hoc_ky(text)
    nh = N.find_nam_hoc(text)
    return ParsedQuery(text=text, khoa=khoa, bac_dao_tao=bac, hoc_ky=hk[0] if hk else None,
                       nam_hoc=f"{nh[0][0]}_{nh[0][1]}" if nh else None,
                       ma_hoc_phan=list(dict.fromkeys(MA_HP_RE.findall(text))), flags=flags)
