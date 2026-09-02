import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import KakaoMap from '../components/map/KakaoMap';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };

const CourseDetail = () => {
  const { courseType, courseId } = useParams();
  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    // 이 effect가 재실행된 뒤(= 더 최신 요청이 시작된 뒤) 도착하는 이전 응답은 무시
    let ignore = false;

    const fetchCourse = async () => {
      setLoading(true);
      setError('');
      try {
        const res = await apiFetch(`/v1/courses/${courseType}/${courseId}`);
        if (ignore) return;
        if (!res.ok) {
          if (res.status === 404) {
            setError('코스 정보를 찾을 수 없어요.');
          } else if (res.status === 401 || res.status === 403) {
            setError('이 코스를 볼 권한이 없어요.');
          } else if (res.status >= 500) {
            setError('서버에 문제가 발생했어요. 잠시 후 다시 시도해주세요.');
          } else {
            setError('코스 정보를 불러오지 못했어요.');
          }
          return;
        }
        const data = await res.json();
        setCourse(data);
      } catch {
        if (!ignore) setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    fetchCourse();

    return () => {
      ignore = true;
    };
  }, [courseType, courseId]);

  if (loading) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status">불러오는 중...</p>
        </main>
      </>
    );
  }

  if (error || !course) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status error">{error || '코스 정보를 찾을 수 없어요.'}</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="course-detail-page">
        <Link to="/courses" className="text-button">
          ← 목록으로
        </Link>

        <div className="course-detail-heading">
          <span className="section-kicker">
            {courseType === 'drnb' ? (course.sigun ?? course.brd_div) : '커스텀 코스'}
          </span>
          <h1>{course.course_name}</h1>
          {courseType === 'custom' && (
            <p className="course-detail-creator">제작자: {course.creator_nickname ?? '알 수 없음'}</p>
          )}
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
            <dd>{course.distance != null ? `약 ${course.distance}km` : '정보 없음'}</dd>
          </div>
          <div>
            <dt>예상 소요시간</dt>
            <dd>
              {course.estimated_time != null ? `약 ${course.estimated_time}분` : '정보 없음'}
            </dd>
          </div>
          <div>
            <dt>완주 인증</dt>
            <dd>{course.has_verification_coords ? '가능' : '불가 (좌표 정보 없음)'}</dd>
          </div>
          {courseType === 'custom' && (
            <div>
              <dt>경유지 수</dt>
              <dd>{course.waypoints?.length ?? 0}개</dd>
            </div>
          )}
        </dl>

        <p className="course-detail-source-note">
          {courseType === 'drnb'
            ? '※ 난이도, 거리, 소요시간은 두루누비 공식 API 기준입니다.'
            : '※ 난이도, 거리, 소요시간은 코스 제작자 기준입니다.'}
        </p>

        {course.course_description && (
          <p className="course-detail-desc">
            {course.course_description.replace(/<br\s*\/?>/gi, '\n')}
          </p>
        )}

        {courseType === 'custom' && course.images?.length > 0 && (
          <div className="course-detail-images">
            {course.images.map((image) => (
              <img key={image.image_id} src={image.image_url} alt={course.course_name} />
            ))}
          </div>
        )}

        {/* DRNB는 시작/종료 좌표만 DB에 있고 전체 경로가 없어서 마커만 표시(직선 경로선은
            실제 트레일과 무관해 오해를 줄 수 있음). 커스텀은 경유지가 다 있어 경로선까지 표시 */}
        {courseType === 'drnb' && course.has_verification_coords && (
          <KakaoMap
            markers={[
              { lat: course.start_lat, lng: course.start_lng, label: '시작' },
              { lat: course.end_lat, lng: course.end_lng, label: '종료' },
            ]}
          />
        )}
        {courseType === 'custom' && course.waypoints?.length > 0 && (
          <KakaoMap
            path={course.waypoints.map((w) => ({ lat: w.latitude, lng: w.longitude }))}
            markers={[
              {
                lat: course.waypoints[0].latitude,
                lng: course.waypoints[0].longitude,
                label: '시작',
              },
              {
                lat: course.waypoints.at(-1).latitude,
                lng: course.waypoints.at(-1).longitude,
                label: '종료',
              },
            ]}
          />
        )}
      </main>
    </>
  );
};

export default CourseDetail;
