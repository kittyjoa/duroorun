import { Link } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { usePaginatedCourses } from '../hooks/usePaginatedCourses';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };
const PAGE_SIZE = 20;

const MyCourses = () => {
  const { user, isLoading: userLoading } = useUser();

  // user 아직 없으면 path를 null로 둬서 훅이 조회를 미룸 ("불러오는 중..." 유지)
  const path = user ? '/v1/courses/custom' : null;
  const buildQuery = (targetPage) =>
    `created_by=${user.user_id}&page=${targetPage}&size=${PAGE_SIZE}`;

  const { courses, total, loading, loadingMore, error, setError, loadMore, removeCourse } =
    usePaginatedCourses(path, buildQuery, [user?.user_id]);

  const handleDelete = async (courseId) => {
    if (!window.confirm('정말 이 코스를 삭제하시겠어요?')) return;
    try {
      const res = await apiFetch(`/v1/courses/custom/${courseId}`, { method: 'DELETE' });
      if (!res.ok) {
        setError('삭제에 실패했어요');
        return;
      }
      removeCourse(courseId);
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    }
  };

  if (!userLoading && !user) {
    return (
      <>
        <Header />
        <main className="course-list-page">
          <p className="course-list-status error">로그인 후 이용할 수 있어요.</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="course-list-page">
        <div className="section-heading">
          <div>
            <span className="section-kicker">나만의 코스</span>
            <h2>내가 만든 코스</h2>
          </div>
          <Link to="/courses/custom/new" className="primary-button">
            코스 만들기
          </Link>
        </div>

        {loading && <p className="course-list-status">불러오는 중...</p>}
        {error && <p className="course-list-status error">{error}</p>}

        {!loading && !error && courses.length === 0 && (
          <p className="course-list-status">아직 만든 코스가 없어요.</p>
        )}

        {!loading && !error && courses.length > 0 && (
          <div className="course-grid">
            {courses.map((course) => (
              <div className="course-card-wrapper" key={course.course_id}>
                <Link
                  to={`/courses/custom/${course.course_id}`}
                  className={`course-card ${DIFFICULTY_COLOR[course.difficulty] ?? 'green'}`}
                >
                  <div className="course-art">
                    <div className="mini-route" />
                    <span className="course-badge">
                      {DIFFICULTY_LABEL[course.difficulty] ?? '난이도 정보 없음'}
                    </span>
                  </div>
                  <div className="course-info">
                    <span>커스텀 코스</span>
                    <h3>{course.course_name}</h3>
                    <p>
                      {course.distance != null && `${course.distance}km · `}
                      {course.estimated_time != null
                        ? `약 ${course.estimated_time}분`
                        : '소요시간 정보 없음'}
                    </p>
                  </div>
                </Link>
                <Link to={`/courses/custom/${course.course_id}/edit`} className="course-card-edit">
                  수정
                </Link>
                <button
                  type="button"
                  className="course-card-delete"
                  onClick={() => handleDelete(course.course_id)}
                >
                  삭제
                </button>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && courses.length < total && (
          <div className="course-list-load-more">
            <button type="button" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? '불러오는 중...' : '더보기'}
            </button>
          </div>
        )}
      </main>
    </>
  );
};

export default MyCourses;
