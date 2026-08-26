import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useDebouncedValue } from '../hooks/useDebouncedValue';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };

// TODO: 더보기 버튼이나 무한스크롤로 20~30개씩 끊어 불러오기 (특히 커스텀)
// 필터 변경하면 페이지 1로 초기화하는 처리도? 더보기 방식이어도?

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

const PAGE_SIZE = 100;

const buildDrnbQuery = (filters) => {
  const params = new URLSearchParams();
  params.set('page', '1');
  params.set('size', String(PAGE_SIZE));
  if (filters.sigun) params.set('sigun', filters.sigun);
  if (filters.difficulty) params.set('difficulty', filters.difficulty);
  if (filters.estimatedTimeMin) params.set('estimated_time_min', filters.estimatedTimeMin);
  if (filters.estimatedTimeMax) params.set('estimated_time_max', filters.estimatedTimeMax);
  return params.toString();
};

const buildCustomQuery = (filters) => {
  const params = new URLSearchParams();
  params.set('page', '1');
  params.set('size', String(PAGE_SIZE));
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

  // 입력창에는 즉시 반영하되, 실제 API 호출은 타이핑이 멈춘 뒤에만 나가도록 지연
  const debouncedDrnbFilters = useDebouncedValue(drnbFilters);
  const debouncedCustomFilters = useDebouncedValue(customFilters);
  // 현재 선택된 코스 유형의 필터만 요청에 태우기 위한 파생값: activeDebouncedFilters
  // 반대쪽 탭의 debounce 값(필터값)이 바뀌어도 파생값의 참조는 유지되고 effect 재실행 X
  const activeDebouncedFilters =
    courseType === 'drnb' ? debouncedDrnbFilters : debouncedCustomFilters;

  useEffect(() => {
    // 이 effect가 재실행된 뒤(= 더 최신 요청이 시작된 뒤) 도착하는 이전 응답은 무시
    let ignore = false;

    const fetchCourses = async () => {
      setLoading(true);
      setError('');
      try {
        const query =
          courseType === 'drnb'
            ? buildDrnbQuery(activeDebouncedFilters)
            : buildCustomQuery(activeDebouncedFilters);
        const path = courseType === 'drnb' ? '/v1/courses/drnb' : '/v1/courses/custom';
        const res = await apiFetch(query ? `${path}?${query}` : path);
        if (ignore) return;
        if (!res.ok) {
          setError('코스 목록을 불러오지 못했어요.');
          return;
        }
        const data = await res.json();
        setCourses(data.items);
      } catch {
        if (!ignore) setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    fetchCourses();

    return () => {
      ignore = true;
    };
  }, [courseType, activeDebouncedFilters]);

  return (
    <>
      <Header />
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
              aria-label="지역 선택"
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
              aria-label="난이도 선택"
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
              aria-label="최소 소요시간(분)"
              value={drnbFilters.estimatedTimeMin}
              onChange={(e) =>
                setDrnbFilters({ ...drnbFilters, estimatedTimeMin: e.target.value })
              }
            />
            <input
              type="number"
              min="0"
              placeholder="최대 소요시간(분)"
              aria-label="최대 소요시간(분)"
              value={drnbFilters.estimatedTimeMax}
              onChange={(e) =>
                setDrnbFilters({ ...drnbFilters, estimatedTimeMax: e.target.value })
              }
            />
          </div>
        ) : (
          <div className="course-filter-bar">
            <select
              aria-label="난이도 선택"
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
              aria-label="최소 거리(km)"
              value={customFilters.distanceMin}
              onChange={(e) =>
                setCustomFilters({ ...customFilters, distanceMin: e.target.value })
              }
            />
            <input
              type="number"
              min="0"
              placeholder="최대 거리(km)"
              aria-label="최대 거리(km)"
              value={customFilters.distanceMax}
              onChange={(e) =>
                setCustomFilters({ ...customFilters, distanceMax: e.target.value })
              }
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
                    {courseType === 'custom' &&
                      course.distance != null &&
                      `${course.distance}km · `}
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
    </>
  );
};

export default CourseList;
