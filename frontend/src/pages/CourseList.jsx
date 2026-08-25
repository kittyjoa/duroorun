import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../api';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };

// 해파랑길 강원 구간(29~50코스)이 지나는 시/군, 삼척→고성 순 (남→북)
// DB에 저장된 sigun 값과 정확히 일치해야 필터가 걸림 (백엔드가 == 비교)
const GANGWON_SIGUN_OPTIONS = [
  '강원 삼척시',
  '강원 동해시',
  '강원 강릉시',
  '강원 양양군',
  '강원 속초시',
  '강원 고성군',
];

const DRNB_INITIAL_FILTERS = {
  sigun: '',
  difficulty: '',
  estimatedTimeMin: '',
  estimatedTimeMax: '',
};

const CUSTOM_INITIAL_FILTERS = {
  difficulty: '',
  distanceMin: '',
  distanceMax: '',
};

const buildDrnbQuery = (filters) => {
  const params = new URLSearchParams();
  if (filters.sigun) params.set('sigun', filters.sigun);
  if (filters.difficulty) params.set('difficulty', filters.difficulty);
  if (filters.estimatedTimeMin) params.set('estimated_time_min', filters.estimatedTimeMin);
  if (filters.estimatedTimeMax) params.set('estimated_time_max', filters.estimatedTimeMax);
  return params.toString();
};

const buildCustomQuery = (filters) => {
  const params = new URLSearchParams();
  if (filters.difficulty) params.set('difficulty', filters.difficulty);
  if (filters.distanceMin) params.set('distance_min', filters.distanceMin);
  if (filters.distanceMax) params.set('distance_max', filters.distanceMax);
  return params.toString();
};

const CourseList = () => {
  const [courseType, setCourseType] = useState('drnb');
  const [drnbFilters, setDrnbFilters] = useState(DRNB_INITIAL_FILTERS);
  const [customFilters, setCustomFilters] = useState(CUSTOM_INITIAL_FILTERS);
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchCourses = async () => {
      setLoading(true);
      setError('');
      try {
        const query =
          courseType === 'drnb' ? buildDrnbQuery(drnbFilters) : buildCustomQuery(customFilters);
        const path = courseType === 'drnb' ? '/v1/courses/drnb' : '/v1/courses/custom';
        const res = await apiFetch(query ? `${path}?${query}` : path);
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
  }, [courseType, drnbFilters, customFilters]);

  return (
    <main className="course-list-page">
      <div className="section-heading">
        <div>
          <span className="section-kicker">코스 찾기</span>
          <h2>어떤 길을 달려볼까요?</h2>
        </div>
      </div>

      <div className="course-type-tabs">
        <button
          type="button"
          className={courseType === 'drnb' ? 'active' : ''}
          onClick={() => setCourseType('drnb')}
        >
          두루누비 공식 코스
        </button>
        <button
          type="button"
          className={courseType === 'custom' ? 'active' : ''}
          onClick={() => setCourseType('custom')}
        >
          커스텀 코스
        </button>
      </div>

      {courseType === 'drnb' ? (
        <div className="course-filter-bar">
          <select
            value={drnbFilters.sigun}
            onChange={(e) => setDrnbFilters({ ...drnbFilters, sigun: e.target.value })}
          >
            <option value="">지역 전체</option>
            {GANGWON_SIGUN_OPTIONS.map((sigun) => (
              <option key={sigun} value={sigun}>
                {sigun}
              </option>
            ))}
          </select>
          <select
            value={drnbFilters.difficulty}
            onChange={(e) => setDrnbFilters({ ...drnbFilters, difficulty: e.target.value })}
          >
            <option value="">난이도 전체</option>
            <option value="EASY">쉬움</option>
            <option value="NORMAL">보통</option>
            <option value="HARD">어려움</option>
          </select>
          <input
            type="number"
            min="0"
            placeholder="최소 소요시간(분)"
            value={drnbFilters.estimatedTimeMin}
            onChange={(e) => setDrnbFilters({ ...drnbFilters, estimatedTimeMin: e.target.value })}
          />
          <input
            type="number"
            min="0"
            placeholder="최대 소요시간(분)"
            value={drnbFilters.estimatedTimeMax}
            onChange={(e) => setDrnbFilters({ ...drnbFilters, estimatedTimeMax: e.target.value })}
          />
        </div>
      ) : (
        <div className="course-filter-bar">
          <select
            value={customFilters.difficulty}
            onChange={(e) => setCustomFilters({ ...customFilters, difficulty: e.target.value })}
          >
            <option value="">난이도 전체</option>
            <option value="EASY">쉬움</option>
            <option value="NORMAL">보통</option>
            <option value="HARD">어려움</option>
          </select>
          <input
            type="number"
            min="0"
            placeholder="최소 거리(km)"
            value={customFilters.distanceMin}
            onChange={(e) => setCustomFilters({ ...customFilters, distanceMin: e.target.value })}
          />
          <input
            type="number"
            min="0"
            placeholder="최대 거리(km)"
            value={customFilters.distanceMax}
            onChange={(e) => setCustomFilters({ ...customFilters, distanceMax: e.target.value })}
          />
        </div>
      )}

      {loading && <p className="course-list-status">불러오는 중...</p>}
      {error && <p className="course-list-status error">{error}</p>}

      {!loading && !error && courses.length === 0 && (
        <p className="course-list-status">조건에 맞는 코스가 없어요.</p>
      )}

      {!loading && !error && courses.length > 0 && (
        <div className="course-grid">
          {courses.map((course) => (
            <Link
              to={`/courses/${courseType}/${course.course_id}`}
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
                <span>
                  {courseType === 'drnb' ? (course.sigun ?? course.brd_div) : '커스텀 코스'}
                </span>
                <h3>{course.course_name}</h3>
                <p>
                  {courseType === 'custom' && course.distance != null && `${course.distance}km · `}
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