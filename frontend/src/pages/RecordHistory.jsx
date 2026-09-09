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
  // 목록 조회 에러(error)와 분리 — 삭제 실패가 이미 불러온 목록을 숨기면 안 됨
  const [deleteError, setDeleteError] = useState('');
  // 삭제 진행 중인 기록 id들 - 단일 값이면 여러 기록을 연달아 삭제할 때 나중 클릭이
  // deletingId를 덮어써서 먼저 클릭한 버튼이 응답 오기 전에 다시 활성화된다. Set으로
  // 두면 기록별로 독립적으로 버튼 비활성화 상태를 관리할 수 있다.
  const [deletingIds, setDeletingIds] = useState(() => new Set());
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
  // 더보기(fetchRecords append)와 삭제 후 재조회(reloadRecords)는 둘 다 records/total을
  // 직접 교체·병합한다 - 동시에 실행되면 requestIdRef 하나로는 늦게 시작한 쪽이 먼저
  // 시작한 쪽을 무조건 stale 처리해버려서, 더보기 버튼이 영영 안 풀리거나(더보기 도중
  // 삭제) 삭제한 기록이 화면에 남는(재조회 도중 더보기) 문제가 생긴다(리뷰 지적). 큐에
  // 넣어 항상 하나씩 순서대로만 실행되게 직렬화한다.
  const listOpQueueRef = useRef(Promise.resolve());
  const runListOpExclusive = (op) => {
    const run = listOpQueueRef.current.then(op, op);
    listOpQueueRef.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  };
  // reloadRecords가 실행 시점(큐 대기 후) 기준 최신 개수를 읽을 수 있도록 미러링한다 -
  // useEffect로 동기화하면 React의 effect는 커밋 후 별도 스케줄(매크로태스크)로 도는
  // 반면 큐는 Promise 체이닝(마이크로태스크)이라 다음 작업이 더 먼저 시작돼버려서 값이
  // 갱신되기 전일 수 있다 - setRecords를 호출하는 자리에서 직접 동기적으로 같이 갱신한다
  const recordsRef = useRef(records);

  const fetchRecords = async (targetPage = 1, { append = false } = {}) => {
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
      // recordsRef.current를 prev로 쓴다 - setRecords(updaterFn)은 이 updater를 렌더링
      // 단계에서 나중에 실행하므로, 여기서 곧바로 recordsRef.current에 동기적으로 반영해야
      // 바로 이어서 큐를 타는 reloadRecords가 최신 개수를 즉시 읽을 수 있다
      let next = data.items;
      if (append) {
        // 방어적으로 한 번 더: ref 가드로 대부분 막히지만, 혹시 모를 중복 병합에도
        // 같은 기록이 목록에 두 번 들어가지 않도록 record_id 기준으로 걸러낸다
        const existingIds = new Set(recordsRef.current.map((r) => r.record_id));
        next = [...recordsRef.current, ...data.items.filter((r) => !existingIds.has(r.record_id))];
      }
      recordsRef.current = next;
      setRecords(next);
      // data.page(요청한 페이지 번호)를 그대로 믿지 않는다 - 삭제 후 재조회 뒤에 큐에
      // 남아있던 더보기 요청이 빈 페이지를 받아도 백엔드는 요청받은 page 번호를 그대로
      // 돌려주므로, 실제로 로드된 개수 기준으로 역산해야 다음 더보기 위치가 안 어긋난다
      // (reloadRecords와 동일한 방식, 리뷰 지적)
      setPage(Math.max(Math.ceil(next.length / RECORD_PAGE_SIZE), 1));
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
      // 이 요청이 stale해진 뒤에 늦게 끝나면 ref를 여기서 풀지 않는다 - stale해진
      // 시점에 effect가 이미 ref를 리셋했고, 그 이후 시작된 요청이 아직 진행 중일 수
      // 있는데 여기서 무조건 풀면 그 진행 중인 요청의 중복 클릭 방지가 풀려버린다.
      if (append && !isStale()) loadingMoreRef.current = false;
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
    if (loadingMoreRef.current) return;
    loadingMoreRef.current = true;
    // 큐에서 대기하는 동안(삭제 후 재조회가 앞에 있는 경우)에도 버튼이 바로 비활성화되고
    // "불러오는 중..."으로 보이도록, fetchRecords가 실제로 시작되기 전에 미리 켜둔다
    setLoadingMore(true);
    setLoadMoreError('');
    runListOpExclusive(() => fetchRecords(page + 1, { append: true }));
  };

  // 삭제 후 재조회 전용 - fetchRecords(1)을 그대로 쓰면 loading을 true로 바꿔 목록이
  // 잠깐 사라진다. MyCourses.jsx(usePaginatedCourses.reload)와 동일하게 loading은
  // 건드리지 않는다. 예전엔 지금까지 불러온 개수만큼 size를 한 번에 늘려서 요청했는데,
  // 백엔드가 size<=100으로 막아놔서 100개 넘게 불러온 뒤 삭제하면 목록이 100개로
  // 잘리면서 page는 그대로라 다음 "더보기"가 잘려나간 구간을 건너뛰는 문제가 있었다
  // (리뷰 지적). 매 요청을 더보기와 똑같은 size(20)로 나눠서 필요한 페이지 수만큼
  // 조회하고, 실제로 받아온 개수 기준으로 page를 다시 계산해 다음 더보기가 정확한
  // 위치를 요청하게 한다. 순차(await 체인)로 하면 페이지 수만큼 왕복시간이 쌓여
  // 기록이 많은 유저일수록 삭제할 때 체감 지연이 길어지므로(리뷰 지적) 병렬로 요청한다.
  const reloadRecords = () =>
    runListOpExclusive(async () => {
      const requestId = ++requestIdRef.current;
      const isStale = () => unmountedRef.current || requestIdRef.current !== requestId;
      const pagesToRefetch = Math.max(Math.ceil(recordsRef.current.length / RECORD_PAGE_SIZE), 1);
      try {
        const responses = await Promise.all(
          Array.from({ length: pagesToRefetch }, (_, i) =>
            apiFetch(`/v1/records/?page=${i + 1}&size=${RECORD_PAGE_SIZE}`)
          )
        );
        if (isStale()) return true;
        if (responses.some((res) => !res.ok)) return false;
        const datas = await Promise.all(responses.map((res) => res.json()));
        if (isStale()) return true;

        // offset 기반 페이지네이션이라 이 병렬 조회 도중 다른 탭/기기에서 새 기록이 생기면
        // 앞 페이지의 마지막 항목이 다음 페이지 offset으로 밀려 들어와 두 번 수집될 수
        // 있다 - record_id 기준으로 걸러 중복 렌더링을 막는다(리뷰 지적). datas는 요청
        // 순서(페이지 오름차순) 그대로 배열에 담기므로 앞쪽 페이지가 우선한다.
        const collectedIds = new Set();
        const collected = [];
        for (const data of datas) {
          for (const record of data.items) {
            if (collectedIds.has(record.record_id)) continue;
            collectedIds.add(record.record_id);
            collected.push(record);
          }
        }
        const latestTotal = datas.at(-1)?.total ?? 0;

        recordsRef.current = collected;
        setRecords(collected);
        setTotal(latestTotal);
        setPage(Math.max(Math.ceil(collected.length / RECORD_PAGE_SIZE), 1));
        return true;
      } catch {
        return isStale();
      }
    });

  const handleDelete = async (recordId) => {
    if (!window.confirm('정말 이 기록을 삭제하시겠어요?')) return;
    setDeleteError('');
    setDeletingIds((prev) => new Set(prev).add(recordId));
    try {
      const res = await apiFetch(`/v1/records/${recordId}`, { method: 'DELETE' });
      if (!res.ok) {
        setDeleteError('삭제에 실패했어요.');
        return;
      }
      const reloaded = await reloadRecords();
      if (!reloaded) {
        setDeleteError('삭제는 됐지만 목록을 새로고침하지 못했어요. 새로고침 해주세요.');
      }
    } catch {
      setDeleteError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(recordId);
        return next;
      });
    }
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
        {/* 목록 조회 에러(error)와 분리 — 삭제 실패가 이미 불러온 목록을 숨기면 안 됨 */}
        {deleteError && <p className="course-list-status error">{deleteError}</p>}

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
                {/* 진행 중(ended_at 없음)인 기록은 다른 탭/기기의 실제 러닝 세션일 수 있어
                    삭제 버튼을 노출하지 않는다 - 지우면 그 세션의 pause/resume/end 요청이
                    404를 맞고 GPS/시간 데이터가 통째로 날아간다(리뷰 지적) */}
                {record.ended_at && (
                  <button
                    type="button"
                    className="record-history-delete"
                    onClick={() => handleDelete(record.record_id)}
                    disabled={deletingIds.has(record.record_id)}
                  >
                    {deletingIds.has(record.record_id) ? '삭제 중...' : '삭제'}
                  </button>
                )}
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
