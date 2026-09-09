from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "local"
    FRONTEND_URL: str = "http://localhost:5173"

    # DB / Redis
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Cookie
    COOKIE_DOMAIN: str = ""

    # OAuth
    OAUTH_STATE_EXPIRE_SECONDS: int = 300  # state TTL 5분 (CSRF 방지용 1회성 값)
    OAUTH_API_TIMEOUT: float = 5.0  # 소셜 API 호출 타임아웃 (초)

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    KAKAO_CLIENT_ID: str = ""
    KAKAO_CLIENT_SECRET: str = ""
    KAKAO_REDIRECT_URI: str = ""

    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    NAVER_REDIRECT_URI: str = ""

    # 두루누비
    DURUNUBI_API_KEY: str = ""
    DURUNUBI_BASE_URL: str = "https://apis.data.go.kr/B551011/Durunubi"

    # 기상청 (단기예보 + 특보) - DURUNUBI_API_KEY와 동일 값 사용
    KMA_API_KEY: str = ""
    KMA_BASE_URL: str = "https://apis.data.go.kr/1360000"

    # 한국관광공사 (위치기반 관광정보) - DURUNUBI_API_KEY와 동일 값 사용
    TOUR_API_KEY: str = ""
    TOUR_BASE_URL: str = "https://apis.data.go.kr/B551011/KorService2"

    # 코스 날씨 브리핑 중 "단기예보 요약 문단 + 기온/상태 통계" 캐시 TTL(초)
    # ㅡ 단기예보 갱신 주기(3시간)와 동일
    WEATHER_BRIEFING_CACHE_TTL_SECONDS: int = 10800
    # 단기예보 조회 자체가 실패해 일부 데이터로만 만든 응답의 캐시 TTL(초)
    # ㅡ 외부 API 일시 장애가 정상 TTL만큼 오래 반영되지 않도록 짧게
    WEATHER_BRIEFING_PARTIAL_FAILURE_CACHE_TTL_SECONDS: int = 300
    # 기상특보 원문 캐시 TTL(초) - 전역(강원 전체) 1개만 캐싱.
    # ㅡ 특보는 언제 새로 발표/해제될지 예측 불가한 긴급 정보라 짧게
    WEATHER_WARNING_RAW_CACHE_TTL_SECONDS: int = 300
    # 특보-코스 지역 관련성 판단 코멘트(Gemini 생성) 캐시 TTL(초) 
    # ㅡ 캐시 키에 특보 원문 해시 있어서 특보 내용 바뀌면 자동으로 갈아치워짐
    # ㅡ 오래된 특보 캐시가 redis에 무한정 남지 않게 하는 안전장치 TTL
    WEATHER_WARNING_COMMENT_CACHE_TTL_SECONDS: int = 3600
    # 주변 관광지 추천 캐시 TTL(초)
    NEARBY_ATTRACTIONS_CACHE_TTL_SECONDS: int = 86400
    # 시작/종료점 중 일부(또는 전체) 관광지 API 호출이 실패한 응답의 캐시 TTL(초)
    # ㅡ 정상 빈 결과와 구분해 짧게 잡아, 장애 복구 후 금방 다시 조회되게
    NEARBY_ATTRACTIONS_PARTIAL_FAILURE_CACHE_TTL_SECONDS: int = 300
    NEARBY_ATTRACTIONS_RADIUS_M: int = 5000

    # 코스 날씨/관광지 엔드포인트는 비로그인 공개 API라 유저 단위 rate limit을 못 쓰고,
    # IP 단위로 건다. 캐시 히트는 카운트 X, "실제로 외부 API 새로 호출하는 경우"만 O
    # ㅡ 두루누비 시딩 배치와 공공데이터포털 쿼터를 공유하므로 남용 방지 안전장치.
    WEATHER_BRIEFING_RATE_LIMIT_MAX_REQUESTS: int = 30
    WEATHER_BRIEFING_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    NEARBY_ATTRACTIONS_RATE_LIMIT_MAX_REQUESTS: int = 30
    NEARBY_ATTRACTIONS_RATE_LIMIT_WINDOW_SECONDS: int = 3600

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    # Redis 락 TTL(60초)보다 확실히 짧게 - 응답이 너무 오래 걸려서 락이 먼저 만료되고
    # 같은 코스에 대한 다른 작업이 끼어드는 걸 막기 위함
    GEMINI_TIMEOUT_SECONDS: int = 30

    # Cloudflare R2
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "duroorun"
    R2_PUBLIC_URL: str = ""

    # 완주 인증 반경 (미터)
    COMPLETION_RADIUS_M: int = 300

    # 이미지 업로드 정책
    COURSE_IMAGE_MAX_COUNT: int = 3
    COURSE_IMAGE_MAX_SIZE_MB: int = 5
    REVIEW_IMAGE_MAX_COUNT: int = 5
    REVIEW_IMAGE_MAX_SIZE_MB: int = 2
    PROFILE_IMAGE_MAX_SIZE_MB: int = 2

    # 프로필 입력 정책
    NICKNAME_MIN_LENGTH: int = 2
    NICKNAME_MAX_LENGTH: int = 10
    LOCATION_MAX_LENGTH: int = 50

    # 리뷰 입력 정책 (Gemini 프롬프트 크기 제한 목적도 겸함)
    REVIEW_CONTENT_MAX_LENGTH: int = 2000

    # 앱 스케줄러 (기본 false — 로컬 서버 켤때마다 두루누비 API 호출되는거 방지.
    # 배포 환경에서는 docker-compose.yml의 backend 서비스에서 true로)
    SEED_ON_STARTUP: bool = False

    # 디스코드 알림 (코스 시드가 재시도 끝에도 실패했을 때)
    DISCORD_WEBHOOK_URL: str = ""

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
