# 두루런 코딩 컨벤션

팀원 전원이 지켜야 할 코딩 규칙입니다.

---

## Python (백엔드)

### 네이밍
- 함수 / 변수: `snake_case`
- 클래스: `PascalCase`
- 상수: `UPPER_SNAKE_CASE`
- ENUM 값: `UPPER_CASE`

### 타입 힌트
- 모든 함수의 파라미터와 리턴 타입 필수
- Optional은 `str | None` 형식 사용 (`Optional[str]` 사용 금지)

```python
# Good
async def get_course(course_id: int) -> CourseResponse:

# Bad
async def get_course(course_id):
```

### Docstring
- 한글로 작성, 함수 첫 줄에 한 줄 설명

```python
async def get_course(course_id: int) -> CourseResponse:
    """코스 상세 정보를 조회합니다."""
```

### Import 순서
1. 표준 라이브러리
2. 서드파티 패키지
3. 로컬 모듈

그룹 사이에 빈 줄을 넣습니다.

```python
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.config import settings
```

### 비동기
- 엔드포인트와 서비스 함수는 모두 `async def`

### 에러 처리
- `HTTPException`으로 통일, 상태 코드와 한글 메시지 포함

```python
raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다.")
```

### 페이지네이션
- 목록 조회는 **offset 페이지네이션**으로 통일 (페이지 번호 방식)
- 쿼리 파라미터: `?page=1&size=20` (page는 1부터 시작)
- 응답에 전체 개수(`total`) 포함하여 프론트가 페이지 수 계산 가능하게

### 매직넘버 상수화
- 이미지 개수/용량 등 정책값은 `config` 상수로 분리 (도메인별로 흩어지지 않게)

```python
REVIEW_IMAGE_MAX_COUNT = 5       # 리뷰 이미지 최대 장수
REVIEW_IMAGE_MAX_SIZE_MB = 2     # 리뷰 이미지 장당 최대 용량(MB)
COURSE_IMAGE_MAX_COUNT = 3       # 커스텀 코스 이미지 최대 장수
COURSE_IMAGE_MAX_SIZE_MB = 5     # 커스텀 코스 이미지 장당 최대 용량(MB)
COMPLETION_RADIUS_M = 300        # 완주 인증 허용 반경(m)
```

### 린터
- **Ruff** 사용, `ruff check app/` 으로 검사
- 한 줄 최대 100자
- PR 올리기 전 반드시 `ruff check app/` 통과 확인

---

## React (프론트엔드)

### 네이밍
- 함수 / 변수: `camelCase`
- 컴포넌트: `PascalCase`
- 상수: `UPPER_SNAKE_CASE`
- 파일명: 컴포넌트는 `PascalCase.jsx`, 유틸/훅은 `camelCase.js`

### 스타일
- 문자열: 작은따옴표(`'`) 사용
- 세미콜론: 사용
- 들여쓰기: 스페이스 2칸

### 컴포넌트
- 함수형 컴포넌트 사용 (`class` 컴포넌트 금지)
- `export default`는 파일 맨 아래에

```jsx
// Good
const CourseCard = ({ course }) => {
  return <div>{course.name}</div>;
};

export default CourseCard;
```

### 비동기
- `async/await` 사용 (`.then()` 체이닝 금지)

```javascript
// Good
const data = await fetchCourse(courseId);

// Bad
fetchCourse(courseId).then(data => { ... });
```

### API 호출
- 공통 API 함수 사용 (Access Token을 `Authorization: Bearer` 헤더에 자동 포함)
- 직접 `fetch` 호출 금지
- httpOnly 쿠키(Refresh Token) 전송을 위해 모든 요청에 `credentials: 'include'` 설정 (공통 API 함수에 적용). 백엔드 CORS는 `allow_credentials=True`
- Access Token 만료(401) 시 `/api/v1/auth/refresh`로 재발급 후 원요청 재시도 로직을 공통 함수에 구현

---

## 주석 규칙

- **한글**로 작성
- "왜" 그렇게 했는지를 설명 (코드가 "무엇"을 하는지는 코드 자체로 표현)

```python
# Good: 이유를 설명
# Soft Delete이므로 DB 트리거가 발동하지 않아 서비스 레이어에서 직접 NULL 처리
await session.execute(
    update(Review).where(Review.user_id == user_id).values(user_id=None)
)

# Bad: 코드를 그대로 반복
# user_id를 None으로 업데이트
await session.execute(
    update(Review).where(Review.user_id == user_id).values(user_id=None)
)
```

---

## Git 규칙

### 커밋 메시지
`[타입] 작업내용` 형식

| 타입 | 설명 | 예시 |
|------|------|------|
| `feat` | 새 기능 | `[feat] 소셜 로그인 구현` |
| `fix` | 버그 수정 | `[fix] 코스 필터 오류 수정` |
| `docs` | 문서 수정 | `[docs] README 업데이트` |
| `refactor` | 코드 리팩토링 | `[refactor] 기록 서비스 로직 정리` |
| `chore` | 설정, 패키지 등 | `[chore] Redis 의존성 추가` |
| `test` | 테스트 코드 | `[test] 유저 인증 테스트 추가` |
| `style` | 꾸미기 | `[style] 랜딩 페이지 로고 추가` |

### 브랜치
- 자기 브랜치에서만 작업
- **main 직접 push 금지**
- PR을 통해서만 main에 머지

```
user_admin
record_review
course_facility
```

### PR
- 최소 **1명 리뷰** 후 머지
- PR 제목도 커밋 메시지와 동일한 형식 사용
- 머지 후 팀원 전체 `git fetch origin && git merge origin/main` 필수
