import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../api';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };

const CourseList = () => {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchCourses = async () => {
      try {
        const res = await apiFetch('/v1/courses/drnb');
        if (!res.ok) {
          setError('코스 목록을 불러오지 못했어요.');
          return;
        }
        const data = await res.json();
        setCourses(data.items);
      } catch {
        setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        setLoading(false);
      }
    };
    fetchCourses();
  }, []);

  return (
    <main className="course-list-page">
      <div className="section-heading">
        <div>
          <span className="section-kicker">두루누비 공식 코스</span>
          <h2>어떤 길을 달려볼까요?</h2>
        </div>
      </div>

      {loading && <p className="course-list-status">불러오는 중...</p>}
      {error && <p className="course-list-status error">{error}</p>}

      {!loading && !error && courses.length === 0 && (
        <p className="course-list-status">등록된 코스가 없어요.</p>
      )}

      {!loading && !error && courses.length > 0 && (
        <div className="course-grid">
          {courses.map((course) => (
            <Link
              to={`/courses/${course.course_id}`}
              className={`course-card ${DIFFICULTY_COLOR[course.difficulty] ?? 'green'}`}
              key={course.course_id}
            >
              <div className="course-art">
                <div className="mini-route" />
                <span className="course-badge">
                  {DIFFICULTY_LABEL[course.difficulty] ?? '난이도 정보 없음'}
                </span>
              </div>
              <div className="course-info">
                <span>{course.sigun ?? course.brd_div}</span>
                <h3>{course.course_name}</h3>
                <p>
                  {course.estimated_time != null
                    ? `약 ${course.estimated_time}분`
                    : '소요시간 정보 없음'}
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
};

export default CourseList;
