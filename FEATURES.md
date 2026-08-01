# 기능 명세 (두루런)

## 서비스 개요

해파랑길을 중심으로 한 한국 해안 트레일 러닝 서비스.
두루누비 공식 코스(DRNB)와 유저가 직접 만든 커스텀 코스를 탐색하고,
완주 기록을 남기고 리뷰를 공유할 수 있는 웹 서비스.

---

## 역할 (user_role)

| 역할 | 설명 |
|------|------|
| `USER` | 일반 유저. 코스 탐색, 러닝 기록, 리뷰 작성, 커스텀 코스 생성 가능 |
| `ADMIN` | 관리자. 편의시설 관리, 리뷰 삭제, 대시보드 통계 조회 가능 |

---

## 기능 목록

### 1. 회원 (인증)

| 기능 | 설명 |
|------|------|
| 소셜 로그인 | Google / Kakao / Naver OAuth 2.0 연동. 이메일/비밀번호 로그인 없음 |
| 로그아웃 | Access Token 블랙리스트 등록 + Refresh Token 삭제 |
| JWT 발급 및 검증 | Access Token + Refresh Token 기반 인증 |
| 토큰 재발급 | Refresh Token으로 Access Token 재발급 (토큰 로테이션) |
| 회원가입 | 소셜 로그인 최초 시 닉네임, 거주지 입력 |
| 회원 탈퇴 | 개인정보 익명화 처리. `deleted_at` 기록. `social_accounts` Hard Delete. **단일 트랜잭션 처리** |

**비즈니스 로직**
- 소셜 로그인 시 `social_accounts`에 `provider_type` + `provider_uid` 저장
- 같은 소셜 계정으로 재가입 시 기존 계정으로 로그인 처리
- 한 유저가 여러 소셜 계정 연동 가능 (Google + Kakao 동시 연동)
- `ADMIN` 계정은 회원가입 API로 생성 불가. seed 스크립트로 별도 생성
- OAuth state는 Redis(`oauth:state:{state}`, TTL 5분)에 저장하여 콜백 시 검증 (CSRF 방지)

**토큰 전략 (JWT)**

| 토큰 | 만료 | 저장 위치 | 전송 방식 |
|------|------|----------|----------|
| Access Token | 30분 | 클라이언트 localStorage | 응답 body(JSON) + 요청 시 `Authorization: Bearer` 헤더 |
| Refresh Token | 14일 | httpOnly 쿠키 (`/api/v1/auth/refresh` 경로 한정) | `Set-Cookie` |

- **세션 정책**: 유저당 Refresh Token 1개 (Redis `refresh:{user_id}`). 재발급 시 기존 토큰을 새 토큰으로 교체(로테이션)
- **재발급 검증**: 클라이언트가 보낸 Refresh의 jti가 Redis 값과 일치할 때만 새 Access + 새 Refresh 발급. 불일치 시 탈취로 간주 → 해당 유저 Refresh 즉시 삭제(강제 로그아웃)
- **로그인/재발급 응답**: Access Token은 응답 body로, Refresh Token은 httpOnly 쿠키(Set-Cookie)로 전달
- **쿠키 환경 분기**: 로컬은 `secure=False`/`samesite=lax`, 프로덕션(HTTPS)은 `secure=True`/`samesite=none`. CORS는 `allow_credentials=True`, 프론트는 `credentials: 'include'` 필수
- **로그아웃**: Access를 `blacklist:{access_jti}`에 잔여 만료시간만큼 등록, Refresh 쿠키 삭제 + Redis `refresh:{user_id}` 삭제

**탈퇴 처리 상세** (단일 트랜잭션으로 일괄 처리)
- `users`: `name`, `nickname`, `profile_image_url`, `location` → NULL 처리, `deleted_at` 기록 (Soft Delete)
- `social_accounts`: Hard Delete (개인 식별 정보 즉시 파기)
- `records`: 서비스 레이어에서 `user_id` 명시적 NULL 업데이트 (기록 보존, 통계 활용)
- `reviews`: 서비스 레이어에서 `user_id` 명시적 NULL 업데이트 (리뷰 내용/평점 보존, 통계 활용). 화면에서는 `WHERE user_id IS NOT NULL`으로 제외
- `courses`: `created_by` → NULL 처리 (커스텀 코스 데이터 100% 보존)
- 위 처리는 하나의 트랜잭션으로 묶어 중간 실패 시 전체 롤백 (social만 삭제되고 user가 남는 불일치 방지)

---

### 2. 프로필 (마이페이지)

| 기능 | 설명 |
|------|------|
| 내 정보 조회 / 수정 | 닉네임, 거주지, 프로필 이미지 수정 가능 |
| 프로필 이미지 업로드 | Cloudflare R2 업로드 후 URL을 `users.profile_image_url`에 저장 |
| 내 러닝 기록 조회 | 완주한 코스 목록, 총 누적 거리, 총 완주 횟수 |
| 내 리뷰 조회 | 작성한 리뷰 목록 |
| 내 커스텀 코스 조회 | 내가 만든 커스텀 코스 목록 |

---

### 3. 코스

#### 3-1. DRNB 코스 (두루누비 공식 코스)

| 기능 | 설명 |
|------|------|
| 코스 목록 조회 | 필터/검색 적용하여 DRNB 코스 목록 조회 |
| 코스 상세 조회 | 코스 상세정보 조회. 시드 스크립트로 저장된 DB 정보만 사용 (배치 갱신) |
| 코스 필터 | 루트/구간(`brd_div`), 지역(`sigun`), 난이도(`difficulty`), 소요시간(`estimated_time`) |
| 편의시설 표시 | 코스 주변 편의시설 지도에 표시 (`course_facility`) |

**두루누비 API 연동**
- 코스 목록/상세에 필요한 정보(`course_name`, `difficulty`, `estimated_time`, `sigun`, `brd_div`, GPX 좌표, 거리, 설명)를 시드 스크립트가 배치로 조회해 DB에 저장. 요청 시점에 두루누비 API를 실시간 호출하지 않음 (API 장애와 무관하게 조회 동작 보장)
- 데이터 최신화 주기 = 시드 스크립트 재실행 주기
- 모든 필터는 DB 값 기준으로 적용

#### 3-2. 커스텀 코스

| 기능 | 설명 |
|------|------|
| 커스텀 코스 등록 | 유저가 직접 코스 생성. 코스명, 거리, 난이도, 소요시간, 설명, 경유지 좌표, 이미지 입력. **경유지 좌표 입력 위해 GPS 권한 필수** |
| 커스텀 코스 이미지 업로드 | Cloudflare R2 업로드. 최대 3개 / 장당 5MB (`COURSE_IMAGE_MAX_COUNT=3`, `COURSE_IMAGE_MAX_SIZE_MB=5`) |
| 커스텀 코스 수정 | 본인만 수정 가능 |
| 커스텀 코스 삭제 | 본인만 삭제 가능. `is_active = false` 처리. 신규 탐색/러닝 시작에서만 제외. 기존 유저 마이페이지 기록 및 관리자 대시보드 통계에는 계속 포함 |
| 커스텀 코스 목록 조회 | 전체 유저가 검색 가능. 난이도, 거리 필터. offset 페이지네이션 |
| 커스텀 코스 상세 조회 | 경유지 좌표(`course_waypoints`) 기반으로 지도에 경로 표시. 코스 주변 편의시설 함께 표시 |

**비즈니스 로직**
- 경유지 좌표는 `course_waypoints`에 `sequence` 순서대로 저장
- 지도에서 좌표를 순서대로 연결하면 실제 경로가 그려짐
- `start_lat/lng`는 `course_waypoints` sequence=1 좌표, `end_lat/lng`는 마지막 sequence 좌표로 자동 저장
- **GPS 권한 필수**: 커스텀 코스 생성은 위치 권한 거부 시 불가
- 탈퇴한 유저의 커스텀 코스는 `created_by = NULL` 처리 후 서비스에 계속 노출

---

### 4. 러닝 기록

| 기능 | 설명 |
|------|------|
| 기록 시작 | 시작 버튼 누르면 `started_at` + 유저 GPS 시작 좌표 기록. **위치 권한 필수** |
| 기록 종료 | 종료 버튼 누르면 `ended_at` + 유저 GPS 종료 좌표 기록. `duration_seconds`, `pace`, `is_completed` 자동 계산 |
| 기록 조회 | 내 러닝 기록 목록 조회 (최신순, offset 페이지네이션 `?page=1&size=20`). 같은 코스 여러 번 달린 히스토리 모두 표시 |
| 기록 삭제 | 본인만 삭제 가능 |
| 기록 일시정지 | 러닝 중 일시정지. `paused_at` 기록 |
| 기록 재시작 | 일시정지 해제, `paused_at` NULL로 초기화 |
| 완주 인증 | GPS 검증 통과 시 `is_completed = true` 자동 처리. 완주 시 해당 코스 리뷰 작성 가능 |
| 페이스 자동 계산 | 평균 페이스 = `duration_seconds / 코스거리(km)` (초/km). 종료 시 자동 계산하여 저장 |

**비즈니스 로직**
- 시작 버튼 → `started_at` + `user_start_lat/lng` 기록
- 종료 버튼 → `ended_at` + `user_end_lat/lng` 기록 → `duration_seconds`, `pace`, `is_completed` 자동 계산
- 일시정지 버튼 → `paused_at` 현재 시각 기록. 이미 일시정지 중이면 400에러
- 재시작 버튼 → `paused_at` NULL로 초기화. 이미 일시정지 상태가 아니면 400에러 
- **완주 인증 (GPS 검증)**: 유저 좌표와 코스 시작/종료점(`courses.start_lat/lng`, `end_lat/lng`)을 하버사인 공식으로 비교
  - 허용 반경: 기본 **300m** (`config` 상수, 코스 담당이 조정 가능)
  - **정방향**: 유저 시작 ≈ 코스 시작 AND 유저 종료 ≈ 코스 종료
  - **역방향**: 유저 시작 ≈ 코스 종료 AND 유저 종료 ≈ 코스 시작 (해안 트레일 양방향 주행 흔함)
  - 정/역방향 중 하나라도 만족하면 완주. 둘 다 불만족(중도하차 등) 시 `is_completed = false`
  - 검증 기준점은 DB에 저장된 좌표만 사용 (런타임에 두루누비 API 미호출 → API 장애와 무관하게 완주 검증 동작)
- **GPS 권한 필수**: 위치 권한 거부 시 러닝 기록 시작 불가 (회원 전부 해당). 완주 검증이 GPS 기반이므로 좌표 없이는 시작 자체를 막음
- **시간 가드**: `duration_seconds` 60초 미만은 완주 미처리(하한), 24시간 초과는 비정상 기록으로 400 Bad Request(상한, 종료 깜빡 방어)
- 거리는 DRNB 코스는 두루누비 API, CUSTOM 코스는 `courses.distance`(km) 사용
- `is_completed = true`인 기록이 있는 유저만 해당 코스 리뷰 작성 가능
- DRNB 코스와 커스텀 코스 모두 기록 가능
- 같은 코스 기록은 횟수 제한 없이 누적 가능 (리뷰 1개 제한과 별개). 마이페이지에서 히스토리로 조회
- `pace` 계산 시 코스 거리가 0이면 에러 방지를 위해 서비스 레이어에서 방어 로직 필요

> v1 한계: 시작/종료 두 지점만 검증하므로 코스 전체 경로 주행은 보장하지 않음 (양 끝점에 직접 가야 하므로 단순 어뷰징은 차단됨). 실시간 경로 추적은 v2에서 도입 예정

---

### 5. 리뷰

| 기능 | 설명 |
|------|------|
| 리뷰 작성 | 완주한 코스에 한해 작성 가능. 리뷰 내용 + 체감 난이도(`EASY`/`NORMAL`/`HARD`) 입력 |
| 리뷰 수정 | 본인만 수정 가능 |
| 리뷰 삭제 | 본인 또는 관리자 삭제 가능 |
| 리뷰 이미지 첨부 | Cloudflare R2 업로드. 최대 5장, 장당 2MB (`REVIEW_IMAGE_MAX_COUNT=5`, `REVIEW_IMAGE_MAX_SIZE_MB=2`) |
| 리뷰 이미지 삭제 | 개별 이미지 삭제 가능. R2에서도 함께 제거 |
| 리뷰 목록 조회 | 코스 상세 페이지에서 해당 코스 리뷰 목록 조회 (최신순, offset 페이지네이션 `?page=1&size=20`) |
| 체감 난이도 평균 표시 | 코스 상세 페이지에서 전체 유저 체감 난이도 평균 표시. 탈퇴 유저 리뷰도 평균 계산에 포함 |
| AI 리뷰 요약 | 코스 리뷰가 3개 이상이면 Gemini가 리뷰를 요약해 코스 상세 페이지에 표시 |

**비즈니스 로직**
- 코스당 리뷰 1개 제한 (UNIQUE INDEX on course_id + user_id). 같은 코스 여러 번 달려도 리뷰는 1개만 작성 가능 (수정은 가능)
- 탈퇴 유저의 리뷰는 화면에 노출하지 않음 (`WHERE user_id IS NOT NULL` 필터링)
- 탈퇴 유저의 리뷰 평점은 체감 난이도 평균 계산에 포함 (통계 목적)
- 관리자 대시보드 "총 리뷰 수" 집계 시 탈퇴 유저 리뷰(`user_id IS NULL`)도 포함 (실제 작성된 리뷰이므로)
- 관리자 삭제 사유: 욕설, 부적절한 내용, 서비스에 악영향을 주는 리뷰

**AI 리뷰 요약 (Gemini)**
- 리뷰가 **3개에 도달하면** 첫 요약 생성. 3개 미만이면 요약 없이 리뷰 원문만 표시
- 이후 새 리뷰가 **5개 추가될 때마다** 재생성 (3 → 8 → 13 ...). 현재 리뷰 수와 `review_summaries.review_count`의 차이가 5 이상이면 갱신
- 요약 결과는 `review_summaries` 테이블에 저장 (코스당 1개, `course_id` UNIQUE). 매 조회마다 Gemini를 호출하지 않고 저장된 요약을 반환
- 요약 대상은 **전체 리뷰** (탈퇴 유저 리뷰 포함 — 난이도 평균과 동일하게 통계성 집계로 취급. 요약문에는 작성자 정보가 들어가지 않음)
- 모델: Gemini 2.5 Flash-Lite (개발 시작 시 최신 모델명 재확인). 연동은 `app/clients/gemini.py`
- 담당: 보류

---

### 6. 편의시설

| 기능 | 설명 |
|------|------|
| 편의시설 목록 조회 | 코스 상세 페이지에서 주변 편의시설 지도 표시 |
| 편의시설 상세 조회 | 카카오맵 API 연동으로 상세 정보 표시 (`kakao_place_id`) |
| 편의시설 등록 | 관리자만 가능. 시설 종류, 이름, 주소, 좌표 입력. 연결할 코스 선택 (선택 사항, 복수 선택 가능) |
| 편의시설 수정 | 관리자만 가능 |
| 편의시설 삭제 | 관리자만 가능. `is_active = false` 처리 |

**편의시설 종류 (`facility_type`)**

| 값 | 설명 |
|----|------|
| `RESTROOM` | 화장실 |
| `PARKING` | 주차장 |
| `LOCKER` | 보관함 |
| `OTHERS` | 기타 |

**비즈니스 로직**
- 편의시설 등록/수정 시 연결할 코스를 선택하면 `course_facility`에 매핑 저장. 코스 연결은 선택 사항
- 편의시설 수정 시 코스 연결 변경 가능 (추가/해제)
- `kakao_place_id` 입력 시 카카오맵 API 조회로 `place_url` 자동 저장
- `kakao_place_id` 없는 편의시설은 우리 DB 정보(이름, 주소)만 표시
- 코스 상세에서 편의시설 조회 시 `facilities.is_active = true`인 것만 JOIN. 비활성화된 편의시설은 `course_facility` 매핑이 남아있어도 화면에 노출하지 않음

---

### 7. 관리자

| 기능 | 설명 |
|------|------|
| 편의시설 CRUD | 편의시설 등록 / 수정 / 삭제 |
| 리뷰 삭제 | 부적절한 리뷰 삭제 (욕설, 부적절한 내용 등) |
| 유저 강제 탈퇴 | 지속적으로 문제가 되는 유저 강제 탈퇴 처리 |
| 대시보드 통계 조회 | 아래 통계 항목 참고 |

**관리자 대시보드 통계 항목**

| 분류 | 항목 |
|------|------|
| 유저 | 총 유저 수, 신규 가입자 수 (일별/주별/월별), 활성 유저 수 (최근 30일), 탈퇴 수 (일별/월별) |
| 러닝 기록 | 총 누적 러닝 거리, 총 완주 횟수, 오늘/이번주/이번달 완주 횟수 |
| 코스 | 전체 인기 코스 TOP 3 (완주 횟수 기준), DRNB 인기 코스 TOP 5, 커스텀 인기 코스 TOP 5, 커스텀 코스 등록 수 |
| 리뷰 | 총 리뷰 수 |
| 편의시설 | 등록된 편의시설 수 (타입별) |

> 탈퇴 수 집계는 `users.deleted_at` 기준  
> 활성 유저는 `records.created_at` 기준 최근 30일 내 기록이 있는 유저  
> 인기 코스는 `records.is_completed = true` 기준 완주 횟수로 집계

---

## 외부 서비스 연동

| 서비스 | 용도 |
|--------|------|
| 두루누비 API (공공데이터포털) | DRNB 코스 상세정보 실시간 조회 (`dmb_id`로 호출) |
| 카카오맵 API | 편의시설 지도 표시, 코스 경로 표시, 장소 상세정보 연동 |
| Google / Kakao / Naver OAuth | 소셜 로그인 |
| Cloudflare R2 | 프로필 이미지, 리뷰 이미지, 커스텀 코스 이미지 저장 |
| Gemini API (Google) | AI 리뷰 요약 생성 (리뷰 3개 이상 코스) |
| Redis | 두루누비 API 응답 캐싱 (TTL 24시간), Access Token 블랙리스트, Refresh Token 저장, OAuth state 저장 |

---

## 미결정 사항

| 항목 | 내용 |
|------|------|
| 두루누비 코스 이미지 | API 응답에 이미지 필드 포함 여부 미확인. 확인 후 반영 |
