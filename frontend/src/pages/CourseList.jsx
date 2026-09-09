import { useState } from 'react';
import { Link } from 'react-router-dom';

import CourseCard from '../components/CourseCard';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePaginatedCourses } from '../hooks/usePaginatedCourses';
import { useSigunOptions } from '../hooks/useSigunOptions';
import { formatCustomSigunBadge } from '../utils/format';

const DRNB_INITIAL_FILTERS = {
  sigun: '',
  difficulty: '',
  distanceMin: '',
  distanceMax: '',
};

const CUSTOM_INITIAL_FILTERS = {
  sigun: '',
  difficulty: '',
  distanceMin: '',
  distanceMax: '',
};

const PAGE_SIZE = 20;

// page/size/difficulty/distance는 공통, sigun은 아직 DRNB만 있어서 먼저 세팅
// ㅡ size는 원래 기본값(20)인데, 더보기 공통 훅에서 reload() 경우처럼 
// 삭제 후 재조회할 때만 기본값 20 말고 현재 화면에 보이던 개수 넘겨줌.
const buildCommonParams = (page, size, filters) => {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('size', String(size));
  if (filters.difficulty) params.set('difficulty', filters.difficulty);
  if (filters.distanceMin) params.set('distance_min', filters.distanceMin);
  if (filters.distanceMax) params.set('distance_max', filters.distanceMax);
  return params;
};

const buildDrnbQuery = (filters, page, size) => {
  const params = buildCommonParams(page, size, filters);
  if (filters.sigun) params.set('sigun', filters.sigun);
  return params.toString();
};

const buildCustomQuery = (filters, page, size) => {
  const params = buildCommonParams(page, size, filters);
  if (filters.sigun) params.set('sigun', filters.sigun);
  return params.toString();
};

const CourseList = () => {
  const { user } = useUser();
  const [courseType, setCourseType] = useState('drnb');
  const [drnbFilters, setDrnbFilters] = useState(DRNB_INITIAL_FILTERS);
  const [customFilters, setCustomFilters] = useState(CUSTOM_INITIAL_FILTERS);
  // 둘 다 실제로 코스가 존재하는 시군만 서버에서 동적으로 받아옴
  const drnbSigunOptions = useSigunOptions('/v1/courses/drnb/sigun-options');
  const customSigunOptions = useSigunOptions('/v1/courses/custom/sigun-options');

  // 입력창에는 즉시 반영하되, 실제 API 호출은 타이핑이 멈춘 뒤에만 나가도록 지연
  const debouncedDrnbFilters = useDebouncedValue(drnbFilters);
  const debouncedCustomFilters = useDebouncedValue(customFilters);
  // 현재 선택된 코스 유형의 필터만 요청에 태우기 위한 파생값: activeDebouncedFilters
  // 반대쪽 탭의 debounce 값(필터값)이 바뀌어도 파생값 참조는 유지되고 훅 내부 effect 재실행 X
  const activeDebouncedFilters =
    courseType === 'drnb' ? debouncedDrnbFilters : debouncedCustomFilters;

  const path = courseType === 'drnb' ? '/v1/courses/drnb' : '/v1/courses/custom';
  const buildQuery = (targetPage, size = PAGE_SIZE) =>
    courseType === 'drnb'
      ? buildDrnbQuery(activeDebouncedFilters, targetPage, size)
      : buildCustomQuery(activeDebouncedFilters, targetPage, size);

  // 탭 전환/필터 변경 시 1페이지부터 다시 조회(목록 교체), "더보기"는 다음 페이지를 이어 붙임
  // ㅡ 훅 내부에서 요청 세대를 관리해 늦게 도착한 응답(예: 더보기 도중 탭 전환)은 버림
  const { courses, total, loading, loadingMore, error, loadMoreError, loadMore } = usePaginatedCourses(
    path,
    buildQuery,
    [courseType, activeDebouncedFilters],
  );

  return (
    <>
      <Header />
      <main className="course-list-page">
        <div className="section-heading">
          <div>
            <span className="section-kicker">코스 찾기</span>
            <h2>어떤 길을 달려볼까요?</h2>
          </div>
          {courseType === 'custom' && user && (
            <Link to="/courses/custom/new" className="primary-button">
              코스 만들기
            </Link>
          )}
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
              {drnbSigunOptions.map((sigun) => (
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
              placeholder="최소 거리(km)"
              aria-label="최소 거리(km)"
              value={drnbFilters.distanceMin}
              onChange={(e) =>
                setDrnbFilters({ ...drnbFilters, distanceMin: e.target.value })
              }
            />
            <input
              type="number"
              min="0"
              placeholder="최대 거리(km)"
              aria-label="최대 거리(km)"
              value={drnbFilters.distanceMax}
              onChange={(e) =>
                setDrnbFilters({ ...drnbFilters, distanceMax: e.target.value })
              }
            />
          </div>
        ) : (
          <div className="course-filter-bar">
            <select
              aria-label="지역 선택"
              value={customFilters.sigun}
              onChange={(e) => setCustomFilters({ ...customFilters, sigun: e.target.value })}
            >
              <option value="">지역 전체</option>
              {customSigunOptions.map((sigun) => (
                <option key={sigun} value={sigun}>
                  {sigun}
                </option>
              ))}
            </select>
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
              <CourseCard
                key={course.course_id}
                course={course}
                to={`/courses/${courseType}/${course.course_id}`}
                badgeText={
                  courseType === 'drnb' ? (course.sigun ?? course.brd_div) : formatCustomSigunBadge(course)
                }
                showMineBadge={courseType === 'custom' && user && course.created_by === user.user_id}
                showCreator={courseType === 'custom'}
              />
            ))}
          </div>
        )}

        {!loading && !error && courses.length < total && (
          <div className="course-list-load-more">
            {loadMoreError && <p className="course-list-status error">{loadMoreError}</p>}
            <button type="button" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? '불러오는 중...' : loadMoreError ? '다시 시도' : '더보기'}
            </button>
          </div>
        )}

        {courseType === 'drnb' && (
          <p className="course-list-footer-note">
            일부 예약/통제구역 코스는 제공하지 않아요. 자세한 내용은{' '}
            <a href="https://durunubi.kr" target="_blank" rel="noreferrer">
              두루누비 공식 홈페이지
            </a>
            를 참고해주세요.
          </p>
        )}
      </main>
    </>
  );
};

export default CourseList;
