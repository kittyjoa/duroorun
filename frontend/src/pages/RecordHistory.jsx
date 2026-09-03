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

  const fetchRecords = async (targetPage = 1, { append = false } = {}) => {
    if (append) {
      setLoadingMore(true);
      setLoadMoreError('');
    } else {
      setLoading(true);
      setError('');
    }
    try {
      const res = await apiFetch(`/v1/records/?page=${targetPage}&size=${RECORD_PAGE_SIZE}`);
      if (unmountedRef.current) return;
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
      if (unmountedRef.current) return;
      setRecords((prev) => (append ? [...prev, ...data.items] : data.items));
      setPage(data.page);
      setTotal(data.total);
    } catch {
      if (!unmountedRef.current) {
        const message = '서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.';
        if (append) {
          setLoadMoreError(message);
        } else {
          setError(message);
        }
      }
    } finally {
      if (!unmountedRef.current) {
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

        {!loading && records.length < total && (
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
