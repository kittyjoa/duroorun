import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { usePaginatedCourses } from '../hooks/usePaginatedCourses';

const BANNED_PAGE_SIZE = 20;
const SEARCH_PAGE_SIZE = 20;

const PROVIDER_LABEL = { KAKAO: '카카오', NAVER: '네이버', GOOGLE: '구글' };
const FACILITY_LABEL = { RESTROOM: '화장실', PARKING: '주차장', LOCKER: '보관함', OTHERS: '기타' };

// 오늘/이번주/이번달/올해 스냅샷 카운트를 작은 통계 카드 하나로 보여줌
const PeriodStatCard = ({ title, counts }) => (
  <div className="admin-stat-card">
    <h3>{title}</h3>
    <dl className="admin-stat-period">
      <div><dt>오늘</dt><dd>{counts.today}</dd></div>
      <div><dt>이번주</dt><dd>{counts.this_week}</dd></div>
      <div><dt>이번달</dt><dd>{counts.this_month}</dd></div>
      <div><dt>올해</dt><dd>{counts.this_year}</dd></div>
    </dl>
  </div>
);

const PopularCourseList = ({ title, items }) => (
  <div className="admin-stat-card">
    <h3>{title}</h3>
    {items.length === 0 ? (
      <p className="course-list-status">아직 완주 기록이 없어요.</p>
    ) : (
      <ol className="admin-popular-course-list">
        {items.map((item) => (
          <li key={item.course_id}>
            <Link to={`/courses/${item.course_type.toLowerCase()}/${item.course_id}`}>
              {item.course_name}
            </Link>
            <span>{item.completion_count}회 완주</span>
          </li>
        ))}
      </ol>
    )}
  </div>
);

const Admin = () => {
  const { user, isLoading: userLoading } = useUser();

  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState('');

  const [unbanningId, setUnbanningId] = useState(null);
  const [unbanError, setUnbanError] = useState('');

  const [nicknameInput, setNicknameInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const isAdmin = user?.user_role === 'ADMIN';

  useEffect(() => {
    if (!isAdmin) return;
    (async () => {
      setStatsLoading(true);
      setStatsError('');
      try {
        const res = await apiFetch('/v1/admin/dashboard');
        if (!res.ok) {
          setStatsError('통계를 불러오지 못했어요.');
          return;
        }
        setStats(await res.json());
      } catch (err) {
        console.error('대시보드 통계 조회 실패:', err);
        setStatsError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        setStatsLoading(false);
      }
    })();
  }, [isAdmin]);

  // usePaginatedCourses는 이름과 달리 {items,total} offset 페이지네이션 응답이면
  // 뭐든 다루는 범용 훅이라 밴 목록에도 그대로 재사용 (course_id가 아닌 id를 key로 씀)
  const bannedPath = isAdmin ? '/v1/admin/banned-accounts' : null;
  const buildBannedQuery = (targetPage, size = BANNED_PAGE_SIZE) => `page=${targetPage}&size=${size}`;
  const {
    courses: bannedAccounts,
    total: bannedTotal,
    loading: bannedLoading,
    loadingMore: bannedLoadingMore,
    error: bannedError,
    loadMoreError: bannedLoadMoreError,
    loadMore: loadMoreBanned,
    reload: reloadBanned,
  } = usePaginatedCourses(bannedPath, buildBannedQuery, [isAdmin]);

  // 검색어를 제출하기 전엔 path를 null로 둬서 전체 유저를 긁어오는 걸 방지
  const searchPath = isAdmin && searchQuery ? '/v1/admin/users/search' : null;
  const buildSearchQuery = (targetPage, size = SEARCH_PAGE_SIZE) =>
    `nickname=${encodeURIComponent(searchQuery)}&page=${targetPage}&size=${size}`;
  const {
    courses: searchResults,
    total: searchTotal,
    loading: searchLoading,
    loadingMore: searchLoadingMore,
    error: searchError,
    loadMoreError: searchLoadMoreError,
    loadMore: loadMoreSearch,
  } = usePaginatedCourses(searchPath, buildSearchQuery, [searchQuery]);

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    setSearchQuery(nicknameInput.trim());
  };

  const handleUnban = async (bannedId) => {
    if (!window.confirm('이 계정의 재가입 차단을 해제할까요?')) return;
    setUnbanError('');
    setUnbanningId(bannedId);
    try {
      const res = await apiFetch(`/v1/admin/banned-accounts/${bannedId}`, { method: 'DELETE' });
      if (!res.ok) {
        setUnbanError('밴 해제에 실패했어요.');
        return;
      }
      const reloaded = await reloadBanned();
      if (!reloaded) {
        setUnbanError('해제는 됐지만 목록을 새로고침하지 못했어요. 새로고침 해주세요.');
      }
    } catch (err) {
      console.error('밴 해제 실패:', err);
      setUnbanError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setUnbanningId(null);
    }
  };

  if (!userLoading && !isAdmin) {
    return (
      <>
        <Header />
        <main className="admin-page">
          <p className="course-list-status error">관리자만 접근할 수 있어요.</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="admin-page">
        <h1>관리자 페이지</h1>

        <section className="admin-section">
          <h2>유저 검색</h2>
          <p className="admin-section-hint">
            닉네임으로 유저를 찾아 프로필로 이동하면 거기서 강제 탈퇴를 진행할 수 있어요.
          </p>
          <form className="admin-search-form" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              value={nicknameInput}
              onChange={(event) => setNicknameInput(event.target.value)}
              placeholder="닉네임 입력"
            />
            <button type="submit" className="primary-button">
              검색
            </button>
          </form>

          {searchQuery && searchLoading && (
            <p className="course-list-status">불러오는 중...</p>
          )}
          {searchQuery && searchError && (
            <p className="course-list-status error">{searchError}</p>
          )}
          {searchQuery && !searchLoading && !searchError && searchResults.length === 0 && (
            <p className="course-list-status">검색 결과가 없어요.</p>
          )}
          {searchQuery && !searchLoading && !searchError && searchResults.length > 0 && (
            <ul className="admin-search-results">
              {searchResults.map((item) => (
                <li key={item.user_id}>
                  <Link to={`/users/${item.user_id}`}>{item.nickname ?? '이름 없음'}</Link>
                  {item.location && <span>{item.location}</span>}
                </li>
              ))}
            </ul>
          )}
          {searchQuery &&
            !searchLoading &&
            !searchError &&
            searchResults.length < searchTotal && (
              <div className="course-list-load-more">
                {searchLoadMoreError && (
                  <p className="course-list-status error">{searchLoadMoreError}</p>
                )}
                <button type="button" onClick={loadMoreSearch} disabled={searchLoadingMore}>
                  {searchLoadingMore ? '불러오는 중...' : searchLoadMoreError ? '다시 시도' : '더보기'}
                </button>
              </div>
            )}
        </section>

        <section className="admin-section">
          <h2>대시보드 통계</h2>
          {(userLoading || statsLoading) && <p className="course-list-status">불러오는 중...</p>}
          {statsError && <p className="course-list-status error">{statsError}</p>}

          {stats && (
            <div className="admin-stat-grid">
              <div className="admin-stat-card">
                <h3>유저</h3>
                <dl className="admin-stat-simple">
                  <div><dt>총 유저 수</dt><dd>{stats.users.total_users}</dd></div>
                  <div><dt>최근 30일 활성 유저</dt><dd>{stats.users.active_users_30d}</dd></div>
                </dl>
              </div>
              <PeriodStatCard title="신규 가입자" counts={stats.users.new_users} />
              <PeriodStatCard title="탈퇴 수" counts={stats.users.withdrawn_users} />

              <div className="admin-stat-card">
                <h3>러닝 기록</h3>
                <dl className="admin-stat-simple">
                  <div><dt>총 누적 거리</dt><dd>{stats.records.total_distance_km.toFixed(1)}km</dd></div>
                  <div><dt>총 완주 횟수</dt><dd>{stats.records.total_completions}회</dd></div>
                </dl>
              </div>
              <PeriodStatCard title="완주 횟수" counts={stats.records.completions} />

              <div className="admin-stat-card">
                <h3>코스</h3>
                <dl className="admin-stat-simple">
                  <div><dt>커스텀 코스 등록 수</dt><dd>{stats.courses.total_custom_courses}</dd></div>
                  <div>
                    <dt>이번달 / 올해 등록</dt>
                    <dd>
                      {stats.courses.custom_course_registrations.this_month} /{' '}
                      {stats.courses.custom_course_registrations.this_year}
                    </dd>
                  </div>
                </dl>
              </div>
              <PopularCourseList title="인기 코스 TOP5 (전체)" items={stats.courses.popular_overall} />
              <PopularCourseList title="인기 코스 TOP3 (DRNB)" items={stats.courses.popular_drnb} />
              <PopularCourseList title="인기 코스 TOP3 (커스텀)" items={stats.courses.popular_custom} />

              <div className="admin-stat-card">
                <h3>리뷰</h3>
                <dl className="admin-stat-simple">
                  <div><dt>총 리뷰 수</dt><dd>{stats.total_reviews}</dd></div>
                </dl>
              </div>

              <div className="admin-stat-card">
                <h3>편의시설</h3>
                <dl className="admin-stat-simple">
                  {Object.entries(stats.facility_counts_by_type).map(([type, count]) => (
                    <div key={type}>
                      <dt>{FACILITY_LABEL[type] ?? type}</dt>
                      <dd>{count}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          )}
        </section>

        <section className="admin-section">
          <h2>밴 목록 ({bannedTotal}건)</h2>
          <p className="admin-section-hint">
            유저 강제 탈퇴는 해당 유저의 프로필 페이지(닉네임 클릭)에서 처리해요.
          </p>

          {bannedLoading && <p className="course-list-status">불러오는 중...</p>}
          {bannedError && <p className="course-list-status error">{bannedError}</p>}
          {unbanError && <p className="course-list-status error">{unbanError}</p>}

          {!bannedLoading && !bannedError && bannedAccounts.length === 0 && (
            <p className="course-list-status">밴된 계정이 없어요.</p>
          )}

          {!bannedLoading && !bannedError && bannedAccounts.length > 0 && (
            <ul className="admin-banned-list">
              {bannedAccounts.map((banned) => (
                <li key={banned.id} className="admin-banned-item">
                  <div>
                    <strong>{banned.banned_nickname ?? '(닉네임 없음)'}</strong>
                    <span>{PROVIDER_LABEL[banned.provider_type] ?? banned.provider_type}</span>
                    <span>{banned.reason}</span>
                    <span className="record-hint">
                      {new Date(banned.banned_at).toLocaleDateString('ko-KR')}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="admin-unban-button"
                    onClick={() => handleUnban(banned.id)}
                    disabled={unbanningId === banned.id}
                  >
                    {unbanningId === banned.id ? '해제 중...' : '밴 해제'}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {!bannedLoading && !bannedError && bannedAccounts.length < bannedTotal && (
            <div className="course-list-load-more">
              {bannedLoadMoreError && (
                <p className="course-list-status error">{bannedLoadMoreError}</p>
              )}
              <button
                type="button"
                onClick={loadMoreBanned}
                // 해제(unban) 처리 중엔 목록이 reloadBanned()로 재조회되는 중이라, 그 사이에
                // 더보기를 누르면 재조회 결과가 무효화되어 해제된 항목이 화면에 남을 수 있음
                disabled={bannedLoadingMore || unbanningId !== null}
              >
                {bannedLoadingMore
                  ? '불러오는 중...'
                  : bannedLoadMoreError
                    ? '다시 시도'
                    : '더보기'}
              </button>
            </div>
          )}
        </section>
      </main>
    </>
  );
};

export default Admin;
