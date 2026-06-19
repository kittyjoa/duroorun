# 데이터베이스 설계

## 기술 스택
- **DB**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.x (asyncio / Mapped 스타일)
- **드라이버**: asyncpg
- **마이그레이션**: Alembic
- **캐시**: Redis (두루누비 API 응답 캐싱)

---

## 마이그레이션 운영 방법

### 모델 변경 후 migration 생성
```bash
alembic revision --autogenerate -m "변경내용_간단히"
alembic upgrade head  # 로컬 반영
```

### 자주 쓰는 명령어
| 명령어 | 설명 |
|--------|------|
| `alembic upgrade head` | 최신 migration까지 적용 |
| `alembic downgrade -1` | 한 단계 롤백 |
| `alembic current` | 현재 적용된 migration 확인 |
| `alembic history` | migration 히스토리 조회 |

### 프로덕션 반영
`deploy.yml`에서 서버 시작 전 `alembic upgrade head`가 자동 실행됩니다.

---

## 외부 API 연동

| 서비스 | 용도 | 비고 |
|--------|------|------|
| 두루누비 API (공공데이터포털) | DRNB 코스 상세정보 (GPX 좌표, 거리, 난이도 등) 실시간 조회 | `dmb_id`로 호출 |
| 카카오맵 API | 편의시설 지도 표시, 장소 상세정보 연동 | `kakao_place_id`로 연동 |
| 소셜 로그인 (Google / Kakao / Naver) | OAuth 2.0 인증 | `social_accounts` 테이블 |
| Cloudflare R2 | 이미지 파일 저장 (리뷰 이미지 / 프로필 이미지 / 코스 이미지) | 확정 |
| Gemini API (Google) | AI 리뷰 요약 생성 | 모델: Gemini 2.5 Flash-Lite (개발 시작 시 최신 모델명 재확인) |

> **두루누비 코스 저장 전략**
> - DRNB 코스는 `courses` 테이블에 `course_id`, `dmb_id`, `course_name`, `difficulty`, `estimated_time`, `sigun`, `brd_div` 저장 (최초 1회 시드 스크립트로 등록)
> - GPX 좌표, 거리, 코스 설명 등 **상세정보는 `dmb_id`로 두루누비 API 실시간 호출**
> - 유저 커스텀 코스는 처음부터 우리 DB에 전체 저장

> **Redis 캐싱 정책**
> - 두루누비 API 응답은 Redis에 캐싱하여 불필요한 외부 API 호출 최소화
> - TTL: 24시간 (코스 정보는 자주 바뀌지 않으므로 길게 설정. 추후 일주일로 조정 가능)
> - 캐시 미스(Redis에 없음) 시에만 두루누비 API 실제 호출 → 결과를 Redis에 저장 후 응답
> - 캐시 키 형식: `durunubi:course:{dmb_id}`
> - **캐시 스탬피드 방지**: 캐시 미스 시 Redis Lock을 걸어 최초 1개 요청만 외부 API 호출. 나머지 요청은 Lock 해제 후 캐시에서 읽도록 처리 (인기 코스 동시 접근 시 외부 API 과부하 방지)
> - JWT 로그아웃 블랙리스트 용도로도 사용

> **Redis 키 정책 (인증/캐싱 통합)**
>
> | 키 형식 | 용도 | TTL |
> |---------|------|-----|
> | `durunubi:course:{dmb_id}` | 두루누비 API 응답 캐싱 | 24시간 |
> | `refresh:{user_id}` | Refresh Token 식별자(jti) 저장. 유저당 1개만 보관(방식 B). 재발급 시 덮어써서 토큰 로테이션 | 14일 |
> | `blacklist:{access_jti}` | 로그아웃/탈퇴된 Access Token 무효화 | 해당 토큰 잔여 만료시간 |
> | `oauth:state:{state}` | 소셜 로그인 OAuth state 검증값 (CSRF 방지) | 5분 |
>
> - **Refresh Token 전략**: 유저당 Refresh Token 1개만 Redis에 보관(`refresh:{user_id}`). 재발급 요청 시 클라이언트가 보낸 토큰의 jti가 Redis 값과 일치할 때만 새 토큰 발급 후 값 교체(로테이션). 불일치 시 탈취로 간주하여 해당 유저 Refresh를 즉시 삭제(강제 로그아웃)
> - **로그아웃/탈퇴**: Access는 `blacklist:{access_jti}`에 잔여 만료시간만큼 등록, Refresh는 `refresh:{user_id}` 삭제

---

## 테이블 목록

| 테이블 | 설명 | ORM 모델 위치 |
|--------|------|---------------|
| `users` | 회원 (일반 / 관리자) | `app/domain/user/models.py` |
| `social_accounts` | 소셜 로그인 연동 (Google / Kakao / Naver) | `app/domain/user/models.py` |
| `courses` | 코스 (DRNB 공식 코스 / 유저 커스텀 코스) | `app/domain/course/models.py` |
| `course_waypoints` | 커스텀 코스 경유지 좌표 | `app/domain/course/models.py` |
| `records` | 러닝 기록 | `app/domain/record/models.py` |
| `reviews` | 코스 리뷰 (완주 코스 한정) | `app/domain/review/models.py` |
| `review_images` | 리뷰 이미지 | `app/domain/review/models.py` |
| `review_summaries` | AI 리뷰 요약 (코스당 1개) | `app/domain/review/models.py` |
| `course_images` | 코스 이미지 (커스텀 코스) | `app/domain/course/models.py` |
| `facilities` | 편의시설 (화장실 / 주차장 / 보관함 등) | `app/domain/facility/models.py` |
| `course_facility` | 코스 ↔ 편의시설 중간 테이블 | `app/domain/facility/models.py` |

---

## 테이블 상세

### users
| 컬럼 | 타입 | 설명 |
|------|------|------|
| user_id | PK | 회원 ID |
| user_role | ENUM | 역할 (`USER` / `ADMIN`). 기본값 `USER` |
| name | VARCHAR(50) nullable | 이름. 탈퇴 시 NULL 처리 |
| nickname | VARCHAR(30) unique nullable | 닉네임. 탈퇴 시 NULL 처리 |
| profile_image_url | VARCHAR nullable | Cloudflare R2 이미지 URL 직접 저장. 탈퇴 시 NULL 처리 |
| location | VARCHAR nullable | 거주지 (시/구 단위). 탈퇴 시 NULL 처리 |
| created_at | TIMESTAMP | 가입일 |
| updated_at | TIMESTAMP nullable | 수정일 |
| deleted_at | TIMESTAMP nullable | 탈퇴일. 탈퇴 시 현재 시각 기록 |

> 소셜 로그인 전용 서비스이므로 `email`, `password` 컬럼 없음. 인증은 `social_accounts`로 관리.  
> `ADMIN` 계정은 회원가입 API로 생성 불가. seed 스크립트로 별도 생성.  
> **탈퇴 처리**: row를 삭제하지 않고 개인정보 컬럼(`name`, `nickname`, `profile_image_url`, `location`)을 NULL로 익명화, `deleted_at`에 탈퇴 시각 기록. 통계용 데이터 보존 목적.

---

### social_accounts
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | PK | ID |
| user_id | FK → users | 회원 |
| provider_type | ENUM | 소셜 로그인 제공자 (`GOOGLE` / `KAKAO` / `NAVER`) |
| provider_uid | VARCHAR | 소셜 제공자 고유 ID |
| created_at | TIMESTAMP | 연동일 |

> UNIQUE INDEX on (provider_type, provider_uid) — 동일 소셜 계정 중복 연동 방지  
> 한 유저가 여러 소셜 계정 연동 가능 (Google + Kakao 동시 연동 허용)  
> **탈퇴 처리**: 개인 식별 정보 파기를 위해 Hard Delete (완전 삭제)

---

### courses
| 컬럼 | 타입 | 설명 |
|------|------|------|
| course_id | PK | 코스 ID |
| course_type | ENUM | 코스 종류 (`DRNB` / `CUSTOM`) |
| dmb_id | VARCHAR nullable | 두루누비 코스 ID. DRNB 코스면 채움, CUSTOM이면 NULL |
| course_name | VARCHAR | 코스 이름 |
| created_by | FK → users nullable | 커스텀 코스 생성 유저. DRNB 코스면 NULL |
| distance | FLOAT nullable | 거리 (**km 단위**). CUSTOM 코스만 저장. DRNB는 API 실시간 조회 |
| difficulty | ENUM nullable | 난이도 (`EASY` / `NORMAL` / `HARD`). DRNB는 시드 스크립트 등록 시 저장. CUSTOM은 유저 입력값 저장 |
| estimated_time | INT nullable | 예상 소요시간 (분). DRNB는 시드 스크립트 등록 시 저장. CUSTOM은 유저 입력값 저장 |
| course_description | TEXT nullable | 코스 설명. CUSTOM 코스만 저장 |
| sigun | VARCHAR nullable | 지역 (시/군). DRNB 코스만 저장 |
| brd_div | VARCHAR nullable | 루트/구간 (예: 해파랑길 1구간). DRNB 코스만 저장 |
| start_lat | FLOAT nullable | 시작 지점 위도 |
| start_lng | FLOAT nullable | 시작 지점 경도 |
| end_lat | FLOAT nullable | 종료 지점 위도 |
| end_lng | FLOAT nullable | 종료 지점 경도 |
| is_active | BOOLEAN | 활성 여부. 기본값 `true` |
| created_at | TIMESTAMP | 등록일 |
| updated_at | TIMESTAMP nullable | 수정일 |

> DRNB 코스의 GPX 좌표, 거리, 상세 설명은 `dmb_id`로 두루누비 API 실시간 조회. 난이도/소요시간/지역/구간은 시드 스크립트 등록 시 DB에 저장  
> CUSTOM 코스의 경유지 좌표는 `course_waypoints` 테이블에 저장  
> `start_lat/lng`, `end_lat/lng`는 DRNB도 저장 (지도 표시 최적화 + **완주 인증 검증 기준점**). **두루누비 API 응답에는 시작/종료 좌표 필드가 없으므로, 시드 스크립트가 `gpxpath`(GPX xml URL)를 다운로드·파싱하여 첫 포인트=시작점, 마지막 포인트=종료점을 추출해 저장.** CUSTOM 코스는 `course_waypoints` 첫/마지막 sequence 기준 자동 저장  
> 완주 인증 검증은 런타임에 두루누비 API를 호출하지 않고 **DB에 저장된 `start_lat/lng`, `end_lat/lng`만 사용** (외부 API 장애와 무관하게 검증 동작 보장)  
> **탈퇴 처리**: `created_by`를 NULL 처리. 코스 데이터와 경유지는 100% 영구 보존 (다른 유저가 계속 이용 가능)

---

### course_waypoints
| 컬럼 | 타입 | 설명 |
|------|------|------|
| waypoint_id | PK | 웨이포인트 ID |
| course_id | FK → courses | 코스 |
| sequence | INT | 순서 (1부터 시작) |
| latitude | FLOAT | 위도 |
| longitude | FLOAT | 경도 |

> CUSTOM 코스 전용. DRNB 코스의 GPX는 두루누비 API에서 실시간 조회  
> UNIQUE INDEX on (course_id, sequence) — 같은 코스 내 순서 중복 방지  
> 지도에서 순서대로 연결하면 실제 경로가 그려짐

---

### records
| 컬럼 | 타입 | 설명 |
|------|------|------|
| record_id | PK | 기록 ID |
| user_id | FK → users nullable | 러너. 탈퇴 시 서비스 레이어에서 명시적 NULL 처리 |
| course_id | FK → courses | 달린 코스 |
| duration_seconds | INT nullable | 총 달린 시간 (초 단위). ended_at - started_at 자동 계산 |
| started_at | TIMESTAMP | 시작 버튼 누른 시각 (자동 기록) |
| ended_at | TIMESTAMP nullable | 종료 버튼 누른 시각 (자동 기록) |
| pace | FLOAT nullable | 평균 페이스 (초/km). `duration_seconds / 코스거리(km)` 자동 계산 |
| user_start_lat | FLOAT nullable | 시작 버튼 누른 시점 유저 GPS 위도 (완주 검증용) |
| user_start_lng | FLOAT nullable | 시작 버튼 누른 시점 유저 GPS 경도 (완주 검증용) |
| user_end_lat | FLOAT nullable | 종료 버튼 누른 시점 유저 GPS 위도 (완주 검증용) |
| user_end_lng | FLOAT nullable | 종료 버튼 누른 시점 유저 GPS 경도 (완주 검증용) |
| is_completed | BOOLEAN | 완주 여부. GPS 검증 통과 시 자동 `true`. 기본값 `false` |
| created_at | TIMESTAMP | 기록 생성일 |

> 시작 버튼 → `started_at` + 유저 시작 좌표(`user_start_lat/lng`) 기록. 종료 버튼 → `ended_at` + 유저 종료 좌표(`user_end_lat/lng`) 기록 + `duration_seconds` / `pace` / `is_completed` 자동 계산  
> **완주 인증 (GPS 검증)**: 코스의 `start_lat/lng`, `end_lat/lng`와 유저 좌표를 하버사인(Haversine) 공식으로 비교. 허용 반경 내(기본 300m, `config` 상수로 코스 담당이 조정 가능)에 들어왔는지 확인. 정방향(유저 시작≈코스 시작 AND 유저 종료≈코스 종료) 또는 역방향(유저 시작≈코스 종료 AND 유저 종료≈코스 시작) 모두 완주 인정 (해안 트레일은 양방향 주행이 흔함)  
> **시간 가드**: `duration_seconds` 60초 미만은 완주 미처리(하한), 24시간 초과는 비정상 기록으로 400 처리(상한, 종료 깜빡 방어)  
> **GPS 권한 필수**: 위치 권한 거부 시 러닝 기록 시작 불가 (완주 검증이 GPS 기반이므로). 시작이 됐다는 것은 GPS 좌표가 확보됐음을 보장  
> 거리는 DRNB 코스는 두루누비 API, CUSTOM 코스는 `courses.distance`(km)에서 가져옴. `actual_distance` 컬럼 없음. `pace` 계산 시 거리가 0이면 서비스 레이어에서 방어  
> 같은 코스 기록은 횟수 제한 없이 누적 가능. 마이페이지에서 히스토리로 조회  
> **탈퇴 처리**: 서비스 레이어에서 `user_id`를 명시적으로 NULL 업데이트. users는 Soft Delete(deleted_at 기록)이므로 DB 트리거 미발동. 기록 데이터는 보존하여 서비스 전체 통계에 활용

---

### reviews
| 컬럼 | 타입 | 설명 |
|------|------|------|
| review_id | PK | 리뷰 ID |
| course_id | FK → courses (index) | 코스 |
| user_id | FK → users nullable (index) | 작성자. 탈퇴 시 서비스 레이어에서 명시적 NULL 처리 |
| contents | TEXT | 리뷰 내용 |
| difficulty_rate | ENUM | 체감 난이도 (`EASY` / `NORMAL` / `HARD`) |
| created_at | TIMESTAMP | 작성일 |
| updated_at | TIMESTAMP nullable | 수정일 |

> 완주(`records.is_completed = true`)한 유저만 해당 코스 리뷰 작성 가능  
> `difficulty_rate`는 유저의 주관적 체감 난이도 — `courses.difficulty`(공식 난이도)와 별도로 표시  
> UNIQUE INDEX on (course_id, user_id) — 일반 유저 간 코스당 리뷰 1개 제한 목적. PostgreSQL에서 NULL은 UNIQUE 제약에서 서로 다른 값으로 취급되므로 탈퇴 유저(`user_id = NULL`) 리뷰가 여러 개 쌓여도 인덱스 충돌 없음  
> **탈퇴 처리**: 서비스 레이어에서 `user_id`를 명시적으로 NULL 업데이트. users는 Soft Delete(deleted_at 기록)이므로 DB 트리거 미발동. 리뷰 내용과 난이도 평점은 보존하되 API 응답에서 제외 (`user_id IS NULL` 필터링). 통계 데이터로만 활용

---

### review_images
| 컬럼 | 타입 | 설명 |
|------|------|------|
| image_id | PK | 이미지 ID |
| review_id | FK → reviews (index) | 리뷰 |
| image_url | VARCHAR | 이미지 URL |
| created_at | TIMESTAMP | 등록일 |

> 리뷰당 최대 5장, 장당 2MB 제한

---

### review_summaries
| 컬럼 | 타입 | 설명 |
|------|------|------|
| summary_id | PK | 요약 ID |
| course_id | FK → courses (UNIQUE) | 코스 (코스당 요약 1개) |
| summary | TEXT | Gemini가 생성한 AI 리뷰 요약문 |
| review_count | INT | 이 요약이 몇 개 리뷰 기준으로 생성됐는지 (갱신 판단용) |
| updated_at | TIMESTAMP | 요약 생성/갱신 시각 |

> 코스 리뷰들을 AI(Gemini)가 요약한 결과를 저장. 코스당 요약 1개이므로 `course_id`에 UNIQUE  
> **생성 조건**: 해당 코스 리뷰가 3개에 도달하면 첫 요약 생성  
> **갱신 주기**: 이후 새 리뷰가 5개 추가될 때마다 재생성 (3 → 8 → 13 ...). 현재 리뷰 수와 `review_count` 차이가 5 이상이면 갱신  
> **요약 대상**: 전체 리뷰 (탈퇴 유저 리뷰 `user_id IS NULL` 포함 — 난이도 평균과 동일하게 통계성 집계로 취급)  
> 위치: 리뷰 도메인 (`app/domain/review/models.py`)

---

### course_images
| 컬럼 | 타입 | 설명 |
|------|------|------|
| image_id | PK | 이미지 ID |
| course_id | FK → courses (index) | 코스 |
| image_url | VARCHAR | 이미지 URL |
| created_at | TIMESTAMP | 등록일 |

> CUSTOM 코스 전용. DRNB 코스 이미지는 두루누비 API 실시간 조회

---

### facilities
| 컬럼 | 타입 | 설명 |
|------|------|------|
| facility_id | PK | 편의시설 ID |
| facility_type | ENUM | 시설 종류 (`RESTROOM` / `PARKING` / `LOCKER` / `OTHERS`) |
| facility_name | VARCHAR | 시설명 |
| facility_address | VARCHAR nullable | 주소 |
| latitude | FLOAT | 위도 |
| longitude | FLOAT | 경도 |
| kakao_place_id | VARCHAR nullable | 카카오맵 장소 ID (상세정보 연동용) |
| place_url | VARCHAR nullable | 카카오맵 장소 URL |
| is_active | BOOLEAN | 활성 여부. 기본값 `true` |
| created_at | TIMESTAMP | 등록일 |
| updated_at | TIMESTAMP nullable | 수정일 |

> 관리자가 직접 등록/관리  
> `kakao_place_id`, `place_url`이 있으면 카카오맵 상세정보 연동 가능

---

### course_facility
| 컬럼 | 타입 | 설명 |
|------|------|------|
| course_id | FK → courses | 코스 |
| facility_id | FK → facilities | 편의시설 |
| created_at | TIMESTAMP | 매핑 연결일 (매핑 추적/디버깅용) |

> PK: (course_id, facility_id) 복합키  
> 코스 ↔ 편의시설 N:M 중간 테이블  
> `created_at`은 관리자가 매핑을 언제 연결했는지 추적하기 위함 (디버깅 목적)

---

## 테이블 관계 요약

```
users          ──< social_accounts
users          ──< courses          (커스텀 코스 생성자)
users          ──< records
users          ──< reviews
courses        ──< course_waypoints (커스텀 코스 경유지)
courses        ──< records
courses        ──< reviews
courses        ──< course_images
courses        ──< course_facility
courses        ──1 review_summaries  (코스당 AI 요약 1개, 1:1)
facilities     ──< course_facility
reviews        ──< review_images
```

---

## 미결정 사항 (추후 논의 필요)

| 항목 | 내용 |
|------|------|
| 두루누비 코스 이미지 | API 응답에 이미지 필드 포함 여부 미확인. 확인 후 반영 |
| GPX URL 접근 방식 | 시드 스크립트 작성 시 `gpxpath` URL에 직접 GET 가능한지 / 별도 인증 헤더 필요한지 확인 필요 |
| 인덱스 추가 | 각 도메인 작업 시 조회 패턴에 맞춰 인덱스 추가 검토 (예: `records.user_id`, `records.course_id`, `records.is_completed`, `courses.course_type/sigun/difficulty`) |

---

## v2 기술 고려사항

| 항목 | 내용 |
|------|------|
| 위경도 PostGIS 전환 | 현재 FLOAT 타입으로 설계. 반경 검색 등 공간 쿼리 필요 시 PostGIS + GeoAlchemy2로 전환 |
| pace 인덱스 추가 | 랭킹 기능 도입 시 `records.pace` 컬럼에 인덱스 추가 |
