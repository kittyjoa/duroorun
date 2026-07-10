"""편의시설 - 비즈니스 로직."""
# TODO update_facility 작성 시: course_ids는 model_dump(exclude_unset=True) 말고
# `if body.course_ids is not None:` 분기로 별도 처리 (None=변경없음, []=전체해제 구분 유지)
# TODO create/get 응답 조립 시: kakao_place_id로 카카오 로컬 API 조회해 place_url 채우기
