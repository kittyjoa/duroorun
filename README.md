# 두루런 (Duroorun)

한국 해안 트레일 러닝 서비스 — 두루누비 공식 코스 탐색, 커스텀 코스 생성, 러닝 기록 관리

> 배포 URL: (추후 추가)

---

## 팀 구성

| 이름 | 역할 | 담당 도메인 |
|------|------|------------|
| 도희 (팀장) | 풀스택 | 회원/인증/관리자/배포 |
| 지영 | 풀스택 | 코스/편의시설 |
| 유선 | 풀스택 | 기록/리뷰+이미지 |

---

## 기술 스택

### 백엔드
- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL 16, SQLAlchemy 2.x async + Alembic
- **Cache**: Redis (두루누비 API 캐싱 / JWT 블랙리스트)
- **Auth**: JWT (소셜 로그인 전용 — Google / Kakao / Naver). Access Token(30분, localStorage) + Refresh Token(14일, httpOnly 쿠키)
- **Storage**: Cloudflare R2
- **AI**: Gemini API (AI 리뷰 요약 — 리뷰 3개 이상 코스)
- **Infra**: Docker, AWS EC2, GitHub Actions (CI/CD)
- **Linter**: Ruff

### 프론트엔드
- **Framework**: React
- **지도**: 카카오맵 API

---

## 초기 세팅 (최초 1회)

> ⚠️ `alembic/`과 `frontend/`(Vite)는 레포에 빈 상태이거나 없을 수 있습니다. 아래 명령어로 초기화해야 합니다. (각각 처음 작업하는 사람이 1회 실행 후 커밋하면, 이후 팀원은 pull만 받으면 됩니다.)

### 1. Alembic 초기화 (DB 마이그레이션)

우리는 async SQLAlchemy(psycopg3)를 쓰므로, `alembic init` 후 생성된 `env.py`를 **async용으로 수정**해야 합니다.

```bash
# 1) async 템플릿으로 초기화
alembic init -t async alembic
```

생성된 `alembic/env.py`를 아래처럼 수정합니다.

```python
# alembic/env.py 상단에 추가
from app.config import settings
from app.database import Base
# 모든 모델을 import 해야 autogenerate가 테이블을 인식함
from app.domain.user import models as user_models       # noqa
from app.domain.course import models as course_models    # noqa
from app.domain.record import models as record_models    # noqa
from app.domain.review import models as review_models    # noqa
from app.domain.facility import models as facility_models  # noqa

# target_metadata를 우리 Base로 연결
target_metadata = Base.metadata

# DB URL을 .env에서 읽어오도록 설정 (alembic.ini에 하드코딩하지 않음)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
```

> `alembic init -t async`로 만들면 `run_migrations_online()`이 이미 async로 생성되므로 별도 수정이 거의 없습니다. URL 연결과 모델 import만 챙기면 됩니다.

초기화 후 첫 마이그레이션:

```bash
alembic revision --autogenerate -m "init tables"
alembic upgrade head
```

### 2. 프론트엔드 (Vite + React) 초기화

```bash
# 1) frontend 폴더에 Vite React 프로젝트 생성
npm create vite@latest frontend -- --template react
cd frontend
npm install
```

> `index.html`, `package.json`, `vite.config.js`, `src/main.jsx`, `src/App.jsx`는 **Vite가 자동 생성**합니다 (레포에 빈 파일로 두지 않음 — 충돌 방지). 초기화 후, 우리 폴더 구조(`src/pages/`, `src/api/`, `src/components/`, `src/hooks/`)를 그 위에 얹어 작업하면 됩니다. `src/pages/*.jsx`, `src/api/index.js`는 우리가 작성하는 파일입니다.

생성 후 `vite.config.js`에 백엔드 프록시를 설정합니다. (개발 중 CORS 우회)

```javascript
// vite.config.js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

공통 API 함수(`src/api/index.js`)에는 **httpOnly 쿠키(Refresh Token) 전송을 위해 `credentials: 'include'`를 반드시 포함**합니다.

```javascript
// src/api/index.js (예시)
const apiFetch = async (url, options = {}) => {
  const accessToken = localStorage.getItem('accessToken');
  return fetch(`/api${url}`, {
    ...options,
    credentials: 'include', // Refresh 쿠키 전송 필수
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken && { Authorization: `Bearer ${accessToken}` }),
      ...options.headers,
    },
  });
};
```

> 카카오맵을 쓰는 페이지는 `index.html`에 카카오맵 SDK 스크립트를 추가해야 합니다.

---

## 로컬 실행

### 1. 환경 설정

```bash
cp .env.example .env
# .env 파일에서 필요한 값 설정
```

### 2-A. pip으로 실행

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 2-B. uv로 실행

```bash
uv sync
uv run uvicorn app.main:app --reload
```

### 2-C. Docker로 실행

```bash
docker compose up --build
```

> Redis도 Docker Compose에 포함되어 있어 별도 설치 불필요

### DB 초기화 동작 방식

| 상황 | 동작 |
|------|------|
| 최초 실행 | 서버 시작 시 `alembic upgrade head` 자동 실행 |
| 모델 변경 후 pull | `alembic upgrade head` 수동 실행 필요 |
| 프로덕션 | `deploy.yml`에서 `alembic upgrade head` 자동 실행 |

### 두루누비 코스 시드 데이터 등록

최초 1회 두루누비 API에서 코스 데이터를 가져와 DB에 저장합니다. 두루누비 API 응답에는 시작/종료 좌표 필드가 없으므로, 시드 스크립트가 `gpxpath`(GPX xml URL)를 다운로드·파싱하여 첫/마지막 포인트를 시작/종료 좌표로 추출해 `courses.start_lat/lng`, `end_lat/lng`에 저장합니다. (이 좌표는 완주 인증 검증의 기준점으로 사용)

```bash
python -m app.scripts.seed_courses
```

### 모델/DB 스키마가 바뀐 직후 pull 받았을 때

```bash
alembic upgrade head
```

에러가 나거나 DB를 완전히 초기화하고 싶으면:

```bash
# DB 초기화 (로컬)
docker compose down -v
docker compose up --build
```

---

## API 문서

서버 실행 후 Swagger UI 확인:

- http://localhost:8000/docs

---

## 린터 (Ruff)

코드 품질 유지를 위해 [Ruff](https://docs.astral.sh/ruff/)를 사용합니다. 설정은 `pyproject.toml`에 정의되어 있습니다.

```bash
# 설치
pip install ruff

# 린트 검사
ruff check app/

# 자동 수정
ruff check app/ --fix

# 코드 포맷팅
ruff format app/
```

> PR 올리기 전 반드시 `ruff check app/` 통과 확인 후 푸시

---

## 프로젝트 구조

```
app/
├── main.py                  # FastAPI 앱 진입점
├── config.py                # 환경변수 설정
├── database.py              # DB 연결 관리
├── redis.py                 # Redis 연결 관리
├── core/
│   └── security.py          # JWT 발급/검증, 블랙리스트
├── api/v1/
│   └── router.py            # API 라우터 통합
├── domain/
│   ├── user/                # 회원/인증/관리자
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   └── service.py
│   ├── course/              # 코스 (DRNB + 커스텀)
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   └── service.py
│   ├── record/              # 러닝 기록
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   └── service.py
│   ├── review/              # 리뷰 + 이미지
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   └── service.py
│   ├── facility/            # 편의시설
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── router.py
│   │   └── service.py
│   └── admin/               # 관리자 대시보드
│       ├── router.py
│       └── service.py
├── clients/
│   ├── r2.py                # Cloudflare R2 파일 업로드/삭제
│   ├── durunubi.py          # 두루누비 API 연동 + Redis 캐싱
│   └── gemini.py            # Gemini API 연동 (리뷰 요약 생성)
└── scripts/
    └── seed_courses.py      # 두루누비 코스 시드 스크립트

frontend/                    # 프론트엔드 (React + Vite)
├── public/
├── src/
│   ├── main.jsx             # 앱 진입점
│   ├── App.jsx              # 라우터 설정
│   ├── api/                 # API 호출 함수
│   │   └── index.js         # 공통 API 헬퍼 (JWT 자동 포함 + credentials)
│   ├── components/          # 공통 컴포넌트
│   ├── pages/               # 페이지 컴포넌트
│   │   ├── Login.jsx
│   │   ├── CourseList.jsx
│   │   ├── CourseDetail.jsx
│   │   ├── RecordStart.jsx
│   │   ├── MyPage.jsx
│   │   └── Admin.jsx
│   └── hooks/               # 커스텀 훅
└── package.json             # Vite 초기화 시 생성

tests/                       # 테스트 (각 도메인 작업 시 추가)
alembic/                     # 마이그레이션 (alembic init 시 생성)

# 루트 설정 파일
.env.example                 # 환경변수 목록 (복사해서 .env로 사용)
.gitignore
requirements.txt             # 파이썬 의존성
pyproject.toml               # Ruff 설정
Dockerfile                   # 백엔드 이미지 (pip 기반)
docker-compose.yml           # PostgreSQL + Redis + 백엔드
alembic.ini                  # Alembic 설정 (alembic init 시 생성)
```

---

## Git 작업 가이드

### 0. Git 명령어 기본 용어

| 용어 | 의미 | 예시 |
|------|------|------|
| `origin` | GitHub 원격 저장소의 별명 | `origin` = `https://github.com/...` |
| `feature/user` | 내 컴퓨터(로컬)의 브랜치 | `git checkout feature/user` |
| `origin/main` | GitHub(원격)의 main 브랜치 | `git merge origin/main` |

**origin을 붙이는 기준:**
- **내 컴퓨터에서 이동**할 때 → origin 안 붙임 (`git checkout feature/user`)
- **GitHub의 코드를 참조**할 때 → origin 붙임 (`git merge origin/main`, `git push origin 내브랜치`)

자주 쓰는 명령어:

| 명령어 | 하는 일 |
|--------|---------|
| `git fetch origin` | GitHub에서 최신 정보를 가져옴 (내 코드는 안 바뀜) |
| `git merge origin/main` | GitHub의 main 코드를 내 브랜치에 합침 |
| `git checkout 브랜치명` | 다른 브랜치로 이동 |
| `git status` | 변경된 파일 목록 확인 |
| `git add 파일명` | 커밋할 파일을 지정 |
| `git commit -m "메시지"` | 변경사항을 저장 (커밋) |
| `git push origin 브랜치명` | 내 커밋을 GitHub에 업로드 |

### 1. 브랜치 전략

```
main ← feature/user
main ← feature/course
main ← feature/record
```

- `main`: 항상 배포 가능한 상태 유지
- `feature/도메인명`: 각자 담당 도메인 브랜치에서 작업

### 2. 커밋 메시지 규칙

| 타입 | 설명 | 예시 |
|------|------|------|
| `feat` | 새 기능 | `[feat] 소셜 로그인 구현` |
| `fix` | 버그 수정 | `[fix] 코스 필터 오류 수정` |
| `docs` | 문서 수정 | `[docs] README 업데이트` |
| `refactor` | 코드 리팩토링 | `[refactor] 기록 서비스 로직 정리` |
| `chore` | 설정, 패키지 등 | `[chore] 의존성 추가` |
| `test` | 테스트 코드 | `[test] 유저 인증 테스트 추가` |

### 3. PR 올리기 전 main 최신화 필수

PR을 올리기 전에 반드시 최신 main을 내 브랜치에 반영해야 합니다.

```bash
git fetch origin
git merge origin/main
# 충돌이 있으면 해결 후 커밋
```

### 4. `git add .` 사용 금지

`git add .`이나 `git add -A`를 사용하면 **본인이 수정하지 않은 파일까지 커밋에 포함**됩니다.

#### 올바른 커밋 순서

```bash
# 1단계: 변경된 파일 목록 확인
git status

# 2단계: 본인이 작업한 파일만 골라서 추가
git add app/domain/course/service.py
git add app/domain/course/router.py

# 3단계: 스테이징된 파일이 내 것만인지 다시 확인
git diff --staged --stat

# 4단계: 커밋
git commit -m "[feat] 코스 필터 API 구현"
```

#### 특정 폴더 안의 파일만 추가하고 싶을 때

```bash
git add app/domain/course/
```

#### 실수로 다른 파일까지 add 했을 때

```bash
# 특정 파일을 스테이징에서 제거 (파일 내용은 유지됨)
git restore --staged app/config.py
```

### 5. 공통 파일 수정 시 팀 공유

아래 파일들은 여러 파트에서 사용하므로, 수정 전에 반드시 팀에 알려주세요.

| 공통 파일 | 역할 |
|-----------|------|
| `app/config.py` | 환경변수 설정 |
| `app/database.py` | DB 연결 관리 |
| `app/redis.py` | Redis 연결 관리 |
| `app/main.py` | FastAPI 앱 진입점 |
| `app/api/v1/router.py` | API 라우터 통합 |
| `requirements.txt` | 패키지 의존성 |

공통 파일 수정이 필요하면:
1. 팀 채팅에 수정 내용 공유
2. **별도 PR로 먼저 머지**
3. 나머지 팀원이 `git fetch origin && git merge origin/main`으로 반영

### 6. 전체 작업 흐름 요약

```
작업 시작
  └─ git fetch origin && git merge origin/main   (최신화)
  └─ 코드 작업
  └─ ruff check app/                              (린트 확인)
  └─ git status                                   (변경 파일 확인)
  └─ git add 내파일만                              (본인 파일만 추가)
  └─ git diff --staged --stat                     (스테이징 확인)
  └─ git commit -m "[타입] 작업내용"               (커밋)
  └─ git fetch origin && git merge origin/main    (PR 전 다시 최신화)
  └─ git push origin 내브랜치                      (푸시)
  └─ GitHub에서 PR 생성 → 팀원 리뷰 → 머지
  └─ 머지 후 전체 팀원 git fetch origin && git merge origin/main
```

---

## 코딩 컨벤션

네이밍, 타입 힌트, Docstring, 주석 규칙 등 상세 컨벤션은 [CONTRIBUTING.md](./CONTRIBUTING.md)를 참고하세요.

---

- `.env` 절대 커밋 금지 (`.gitignore`에 포함). `.env.example`로 필요한 변수 목록만 공유
- JWT: Access Token(30분, localStorage) + Refresh Token(14일, httpOnly 쿠키). Refresh는 유저당 1개 저장(Redis `refresh:{user_id}`), 재발급 시 토큰 로테이션
- 로그아웃/탈퇴 시 Access는 Redis 블랙리스트(`blacklist:{access_jti}`) 등록, Refresh는 Redis에서 삭제
- Refresh 쿠키는 `/api/v1/auth/refresh` 경로 한정. 환경 분기: 로컬 `secure=False`/`samesite=lax`, 프로덕션 `secure=True`/`samesite=none`
- CORS 허용 주소 명시 (`*` 사용 금지, 우리 프론트 주소만 허용). httpOnly 쿠키 사용으로 `allow_credentials=True` 필수, 프론트는 `credentials: 'include'`
- 소셜 로그인 OAuth state 검증 필수 (CSRF 방지). state는 Redis(`oauth:state:{state}`, TTL 5분) 저장
- API 소유권 검증 필수 (본인 리소스만 수정/삭제 가능. `user_id` 검증 챙기기)

---

## 개발 팁

### R2 이미지 삭제 순서
DB 트랜잭션 성공(commit) 후에 R2 삭제 API 호출. 트랜잭션 실패 시 R2 파일만 지워지는 현상 방지.
