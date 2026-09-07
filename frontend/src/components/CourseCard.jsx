import { Link } from 'react-router-dom';

// CourseList/MyCourses 공통 난이도 표시 — 두 페이지에 중복 정의돼 있던 걸 여기로 통합
export const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
export const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };

// 코스 목록(전체 코스/나만의 코스)에서 공통으로 쓰는 카드.
// 두 페이지가 다른 부분(링크 대상, 뱃지 문구, 제작자 표시, 수정/삭제 버튼)만
// props로 받아 처리 — 마크업/클래스명은 완전히 동일하게 유지(CSS 영향 없음)
const CourseCard = ({ course, to, badgeText, showMineBadge = false, showCreator = false, actions = null }) => (
  <div className="course-card-wrapper">
    <Link to={to} className={`course-card ${DIFFICULTY_COLOR[course.difficulty] ?? 'green'}`}>
      <div className="course-art">
        <div className="mini-route" />
        {showMineBadge && <span className="course-card-mine">내 코스</span>}
      </div>
      <div className="course-info">
        <span>
          {badgeText}
          <span className="course-badge">
            {DIFFICULTY_LABEL[course.difficulty] ?? '난이도 정보 없음'}
          </span>
        </span>
        <h3>{course.course_name}</h3>
        <p>
          {course.distance != null && `${course.distance}km · `}
          {course.estimated_time != null ? `약 ${course.estimated_time}분` : '소요시간 정보 없음'}
        </p>
        {showCreator && <p>제작자: {course.creator_nickname ?? '알 수 없음'}</p>}
      </div>
    </Link>
    {actions}
  </div>
);

export default CourseCard;
