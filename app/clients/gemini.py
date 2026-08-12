"""Gemini API 연동 (리뷰 요약 생성)."""

from functools import lru_cache

from google import genai
from google.genai.client import Client

from app.config import settings

_SUMMARY_PROMPT = """다음은 한 러닝 코스에 달린 유저 리뷰들입니다.
전체 내용을 종합해서 2~3문장으로 자연스럽게 요약해주세요.
개별 작성자를 언급하거나 인용하지 말고, 코스의 전반적인 특징과 평가를 요약해주세요.
**, #, - 같은 마크다운 서식은 쓰지 말고 순수 텍스트로만 답변해주세요.

리뷰 목록:
{reviews}
"""


@lru_cache
def _get_client() -> Client:
    return genai.Client(api_key=settings.GEMINI_API_KEY)


async def summarize_reviews(review_contents: list[str]) -> str:
    """리뷰 내용 목록을 Gemini로 요약합니다.

    API 실패 시 google.genai.errors.APIError가 발생합니다.
    """
    reviews_text = "\n".join(f"- {content}" for content in review_contents)
    prompt = _SUMMARY_PROMPT.format(reviews=reviews_text)
    response = await _get_client().aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )
    return response.text
