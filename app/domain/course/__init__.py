# course.models와 facility.models는 서로를 문자열로 참조하는 relationship이 있어(course_facilities),
# 둘 중 하나만 단독으로 import되면 SQLAlchemy가 매퍼 설정 시 상대 클래스명을 못 찾아 에러남.
# 어느 쪽이 먼저 import되든 나머지 한쪽도 함께 로드되도록 서로를 import해 둠.
from app.domain.facility import models as _facility_models  # noqa
