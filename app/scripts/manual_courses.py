"""두루누비 courseList API가 반환하지 않는 강원 해파랑길 코스 수동 데이터.

ㅡ 두루누비 Open API가 일부 강원 해파랑길 코스를 누락해서 반환.
(팀장님이 운영 기관에 문의, 답변 대기중)
ㅡ manual_course.py: durunubi.kr 코스 상세 페이지 내용 임시 하드코딩.
seed_courses.py가 API 응답과 병합해서 사용.
ㅡ manual_courses_gpx 폴더: 사이트에서 다운받은 6개 코스 gpx 파일
ㅡ API가 나중에 이 코스를 정상적으로 반환하기 시작하면,
시드파일의 _merge_manual_courses 로직이 자동으로 API 데이터 우선시함.
ㅡ 수집일: 2026-08-05
ㅡ 공공누리 "출처표시+상업적이용금지+변경금지" 조건에 따라 이용 가능한 정보들
"""

from pathlib import Path

_GPX_DIR = Path(__file__).parent / "manual_courses_gpx"

# crsLevel: "1"=EASY, "2"=NORMAL, "3"=HARD
# crsTotlRqrmHour: 필드명은 "Hour"지만 API 관례상 분 단위 (예: 8시간 = "480")
MANUAL_COURSES: list[dict] = [
    {
        "crsIdx": "T_CRS_MNG0000004201",
        "crsKorNm": "해파랑길 29코스",
        "crsDstnc": "18.0",
        "crsLevel": "2",
        "crsTotlRqrmHour": "450",
        "crsContents": (
            "삼척 동해 구간 중 원덕읍과 근덕면을 잇는 길이며, 호산 터미널에서 용화리까지 연결된다. "
            "둑길과 산길, 고갯길을 지나며 황희정승 명승지와 휴양림을 거치는 구간이다."
        ),
        "sigun": "강원 삼척시",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004201.gpx",
    },
    {
        "crsIdx": "T_CRS_MNG0000004204",
        "crsKorNm": "해파랑길 32코스",
        "crsDstnc": "21.9",
        "crsLevel": "2",
        "crsTotlRqrmHour": "480",
        "crsContents": (
            "해파랑길의 32번째 코스로 삼척 동해 구간 중 삼척시 근덕면에서 동해시 추암동을 잇는 길. "
            "바닷길과 오십천 강변길, 하천길과 산촌마을 등 다채로운 길을 지나간다."
        ),
        "sigun": "강원 삼척시",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004204.gpx",
    },
    {
        "crsIdx": "T_CRS_MNG0000004208",
        "crsKorNm": "해파랑길 36코스 바우길 08구간",
        "crsDstnc": "8.9",
        "crsLevel": "3",
        "crsTotlRqrmHour": "330",
        "crsContents": (
            "정동진역에서 출발해 183고지, 패러글라이딩 활공장을 지나 안인해변에 이르는 길이다. "
            "해안길을 지나 바다를 보며 괘방산 등산로를 지나는 구간으로, "
            "등산로를 지나므로 체력을 요하는 도전적인 코스이다."
        ),
        "sigun": "강원 강릉시",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004208.gpx",
    },
    {
        "crsIdx": "T_CRS_MNG0000004337",
        "crsKorNm": "해파랑길 37코스 바우길 07구간",
        "crsDstnc": "16.1",
        "crsLevel": "2",
        "crsTotlRqrmHour": "330",
        "crsContents": (
            "해파랑길의 37번째 코스이자 강릉구간이며 바우길 07구간이다. "
            "안인해변에서 출발해 오독떼기전수관으로 이어지는 길로, "
            "굴산사지당간지주 등 다양한 볼거리가 많은 강릉의 내륙 정취를 맛볼 수 있는 구간이다."
        ),
        "sigun": "강원 강릉시",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004337.gpx",
    },
    {
        "crsIdx": "T_CRS_MNG0000004209",
        "crsKorNm": "해파랑길 38코스 바우길 06구간",
        "crsDstnc": "17.9",
        "crsLevel": "2",
        "crsTotlRqrmHour": "390",
        "crsContents": (
            "오독떼기전수관에서 출발해 모산봉, 중앙시장을 거쳐 솔바람다리까지 이어지는 길이다. "
            "강릉의 전형적인 농촌마을과 전통시장, 낙락장송 산책길로 조성되어 있으며, "
            "내륙을 관통하는 길로 길찾기에 어려움이 있을 수 있어 주의가 필요하다."
        ),
        "sigun": "강원 강릉시",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004209.gpx",
    },
    {
        "crsIdx": "T_CRS_MNG0000004212",
        "crsKorNm": "해파랑길 43코스",
        "crsDstnc": "9.4",
        "crsLevel": "1",
        "crsTotlRqrmHour": "210",
        "crsContents": (
            "하조대 해변에서 출발해 여운포교와 동호해변을 지나 수산항에 이르는 길이다. "
            "인적이 드문 길게 이어진 해안길로 양양의 숨은 절경을 만날 수 있는 코스이다."
        ),
        "sigun": "강원 양양군",
        "brdDiv": "DNWW",
        "gpx_path": _GPX_DIR / "T_CRS_MNG0000004212.gpx",
    },
]
