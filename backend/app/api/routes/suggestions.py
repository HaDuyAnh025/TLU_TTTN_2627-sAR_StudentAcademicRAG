from fastapi import APIRouter, Query

from app.schemas.api import SuggestionsResponse
from app.services.suggestion_service import get_suggestions

router = APIRouter(tags=["suggestions"])


@router.get("/suggestions", response_model=SuggestionsResponse, summary="Câu hỏi gợi ý cho màn hình chat")
def suggestions(
    limit: int = Query(6, ge=1, le=50),
    category: str | None = Query(
        None, description="dang_ky_hoc_phan | hoc_phi | tot_nghiep | hoc_bong | thu_tuc | lich_thi"
    ),
) -> SuggestionsResponse:
    return SuggestionsResponse(items=get_suggestions(limit, category))
