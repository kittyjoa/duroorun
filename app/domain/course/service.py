"""코스 (DRNB + 커스텀) - 비즈니스 로직."""
# update_course 코스 수정 함수 작성할때 model_dump(exclude_unset=True) 넣고 주석도 넣기
# (주석: 요청 JSON에 실제 포함된 필드만 딕셔너리로 뽑음. 생략 필드는 안 건드리고 명시적 null만 반영.)

# TODO DRNB 목록/조회 함수 작성 시: 쿼리에 WHERE course_type == CourseType.DRNB 필터 반드시 포함할 것.
