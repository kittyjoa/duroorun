import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiFetch } from '../api';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };

const CourseDetail = () => {
  const { courseType, courseId } = useParams();
  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchCourse = async () => {
      setLoading(true);
      setError('');
      try {
        const res = await apiFetch(`/v1/courses/${courseType}/${courseId}`);
        if (!res.ok) {
          setError('코스 정보를 찾을 수 없어요.');
          return;
        }
        const data = await res.json();
        setCourse(data);
      } catch {
        setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        setLoading(false);
      }
    };
    fetchCourse();
  }, [courseType, courseId]);

  if (loading) {
    return (
      <main className="course-detail-page">
        <p className="course-list-status">불러오는 중...</p>
      </main>
    );
  }

  if (error || !course) {
    return (
      <main className="course-detail-page">
        <p className="course-list-status error">{error || '코스 정보를 찾을 수 없어요.'}</p>
      </main>
    );
  }

  return (
    <main className="course-detail-page">
      <Link to="/courses" className="text-button">
        ← 목록으로
      </Link>

      <div className="course-detail-heading">
        <span className="section-kicker">
          {courseType === 'drnb' ? (course.sigun ?? course.brd_div) : '커스텀 코스'}
        </span>
        <h1>{course.course_name}</h1>
      </div>

      <dl className="course-detail-info">
        <div>
          <dt>난이도</dt>
          <dd>{DIFFICULTY_LABEL[course.difficulty] ?? '정보 없음'}</dd>
        </div>
        <div>
          <dt>평균 체감 난이도</dt>
          <dd>{DIFFICULTY_LABEL[course.average_difficulty] ?? '리뷰 없음'}</dd>
        </div>
        <div>
          <dt>거리</dt>
          <dd>{course.distance != null ? `${course.distance}km` : '정보 없음'}</dd>
        </div>
        <div>
          <dt>예상 소요시간</dt>
          <dd>
            {course.estimated_time != null ? `약 ${course.estimated_time}분` : '정보 없음'}
          </dd>
        </div>
        {courseType === 'drnb' && (
          <div>
            <dt>완주 인증</dt>
            <dd>{course.has_verification_coords ? '가능' : '불가 (좌표 정보 없음)'}</dd>
          </div>
        )}
        {courseType === 'custom' && (
          <div>
            <dt>경유지 수</dt>
            <dd>{course.waypoints?.length ?? 0}개</dd>
          </div>
        )}
      </dl>

      {course.course_description && <p className="course-detail-desc">{course.course_description}</p>}

      {courseType === 'custom' && course.images?.length > 0 && (
        <div className="course-detail-images">
          {course.images.map((image) => (
            <img key={image.image_id} src={image.image_url} alt={course.course_name} />
          ))}
        </div>
      )}
    </main>
  );
};

export default CourseDetail;