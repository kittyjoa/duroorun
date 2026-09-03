import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { formatElapsed, formatPace } from '../utils/format';

const formatDate = (isoString) => {
  const date = new Date(isoString);
  return date.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
};

const RECORD_PAGE_SIZE = 20;

const RecordHistory = () => {
  const navigate = useNavigate();
  const { user, isLoading: userLoading } = useUser();
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  // "더보기" 실패는 error(초기 로딩 에러)와 분리한다 - error를 같이 쓰면 render 조건이
  // !error를 요구해서, 더보기만 실패해도 이미 불러온 목록 전체가 화면에서 사라져버린다
  const [loadMoreError, setLoadMoreError] = useState('');
  // 컴포넌트가 언마운트된 뒤 도착하는 응답이 setState를 시도하지 않도록 막는다
  const unmountedRef = useRef(false);
  // unmountedRef만으로는 "어떤 요청이 최신인지"를 구분하지 못한다 - StrictMode의
  // 마운트→클린업→마운트나 userLoading/user 변화로 이 effect가 여러 번 실행되면,
  // 먼저 시작된 요청이 늦게 도착했을 때도 unmountedRef.current가 (다음 실행이 이미
  // false로 되돌려놨으므로) false라서 최신 상태를 덮어쓸 수 있었다. 요청마다 번호를
  // 매겨서 가장 최근 요청의 응답만 반영한다.
  const requestIdRef = useRef(0);
  // loadingMore(state)는 setState 직후 리렌더 전까지 반영되지 않아, "더보기" 버튼이
  // disabled 되기 전에 연달아 두 번 클릭되면 fetchRecords가 중복 실행될 수 있다 -
  // ref는 동기적으로 바로 갱신되므로 클릭 시점에 즉시 막을 수 있다.
  const loadingMoreRef = useRef(false);

  const fetchRecords = async (targetPage = 1, { append = false } = {}) => {
    if (append) {
      if (loadingMoreRef.current) return;
      loadingMoreRef.current = true;
    }
    const requestId = ++requestIdRef.current;
    const isStale = () => unmountedRef.current || requestIdRef.current !== requestId;

    if (append) {
      setLoadingMore(true);
      setLoadMoreError('');
    } else {
      setLoading(true);
      setError('');
    }
    try {
      const res = await apiFetch(`/v1/records/?page=${targetPage}&size=${RECORD_PAGE_SIZE}`);
      if (isStale()) return;
      if (!res.ok) {
        const message =
          res.status === 401
            ? '로그인이 필요해요.'
            : append
              ? '기록을 더 불러오지 못했어요.'
              : '러닝 기록을 불러오지 못했어요.';
        if (append) {
          setLoadMoreError(message);
        } else {
          setError(message);
        }
        return;
      }
      const data = await res.json();
      if (isStale()) return;
      setRecords((prev) => {
        if (!append) return data.items;
        // 방어적으로 한 번 더: ref 가드로 대부분 막히지만, 혹시 모를 중복 병합에도
        // 같은 기록이 목록에 두 번 들어가지 않도록 record_id 기준으로 걸러낸다
        const existingIds = new Set(prev.map((r) => r.record_id));
        return [...prev, ...data.items.filter((r) => !existingIds.has(r.record_id))];
      });
      setPage(data.page);
      setTotal(data.total);
    } catch {
      if (!isStale()) {
        const message = '서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.';
        if (append) {
          setLoadMoreError(message);
        } else {
          setError(message);
        }
      }
    } finally {
      // 중복 클릭 방지용 ref는 staleness와 무관하게 이 요청이 끝나면 바로 풀어준다 -
      // 화면에 반영되든 안 되든, "지금 진행 중인 더보기 요청"은 끝난 것이기 때문이다.
      if (append) loadingMoreRef.current = false;
      // 로딩 플래그는 이 요청 자신이 최신일 때만 끈다 - append(더보기) 쪽은 CourseDetail의
      // fetchReviews와 동일하게, effect가 다시 실행될 때(아래) 명시적으로 리셋해준다.
      if (!isStale()) {
        if (append) {
          setLoadingMore(false);
        } else {
          setLoading(false);
        }
      }
    }
  };

  useEffect(() => {
    if (!userLoading && !user) {
      navigate('/login', { replace: true });
    }
  }, [userLoading, user, navigate]);

  useEffect(() => {
    if (userLoading || !user) return undefined;
    // StrictMode(개발 모드)가 effect를 마운트→클린업→마운트 순으로 두 번 실행하므로,
    // 매 실행 시작 시점에 반드시 false로 되돌려야 두 번째 실행의 응답이 무시되지 않는다
    unmountedRef.current = false;
    // 이전 실행에서 "더보기" 요청이 진행 중이었다면(예: userLoading/user 값이 다시
    // 바뀌어 이 effect가 재실행된 경우), 그 요청은 이제 stale이라 finally에서 더 이상
    // 풀어주지 않으므로 여기서 명시적으로 리셋한다 - 안 그러면 "더보기" 버튼이 계속
    // disabled로 남는다. 남아있던 이전 "더보기" 실패 메시지도 함께 지운다 - 첫 페이지를
    // 다시 불러오는 성공적인 조회 뒤에 옛 에러가 남아있으면 안 된다.
    setLoadingMore(false);
    loadingMoreRef.current = false;
    setLoadMoreError('');
    fetchRecords(1);
    return () => {
      unmountedRef.current = true;
    };
  }, [userLoading, user]);

  const handleLoadMore = () => {
    fetchRecords(page + 1, { append: true });
  };

  return (
    <>
      <Header />
      <main className="course-detail-page">
        <div className="course-detail-heading">
          <span className="section-kicker">러닝 기록</span>
          <h1>내 러닝 히스토리</h1>
        </div>

        {loading && <p className="course-list-status">불러오는 중...</p>}
        {error && <p className="course-list-status error">{error}</p>}

        {!loading && !error && records.length === 0 && (
          <p className="course-list-status">아직 러닝 기록이 없어요.</p>
        )}

        {!loading && !error && records.length > 0 && (
          <ul className="record-history-list">
            {records.map((record) => (
              <li key={record.record_id} className="record-history-item">
                <div className="record-history-main">
                  <strong>{record.course_name}</strong>
                  <span className="record-hint">{formatDate(record.started_at)}</span>
                </div>
                <div className="record-history-stats">
                  <span>{formatElapsed(record.duration_seconds)}</span>
                  <span>{formatPace(record.pace)}</span>
                  {record.ended_at ? (
                    <span className={record.is_completed ? 'record-badge success' : 'record-badge'}>
                      {record.is_completed ? '완주' : '미완주'}
                    </span>
                  ) : (
                    // 아직 종료되지 않은(다른 탭/기기에서 진행 중이거나, 종료 전 페이지를
                    // 나간) 기록은 미완주가 아니라 진행 중이라고 보여줘야 한다
                    <span className="record-badge">진행 중</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {loadMoreError && <p className="course-list-status error">{loadMoreError}</p>}

        {!loading && !error && records.length < total && (
          <button
            type="button"
            className="text-button review-load-more"
            onClick={handleLoadMore}
            disabled={loadingMore}
          >
            {loadingMore ? '불러오는 중...' : '기록 더보기'}
          </button>
        )}

        <Link to="/courses" className="text-button">
          코스 찾아보기 →
        </Link>
      </main>
    </>
  );
};

export default RecordHistory;
