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
    OAUTH_API_TIMEOUT: float = 5.0         # 소셜 API 호출 타임아웃 (초)

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

    # 카카오맵
    KAKAO_MAP_API_KEY: str = ""

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

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

    # 앱 스케줄러 (기본 false — 로컬 서버 켤때마다 두루누비 API 호출되는거 방지.
    # 배포 환경에서는 docker-compose.yml의 backend 서비스에서 true로)
    SEED_ON_STARTUP: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
