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
  const [total, setTotal] = useState(0);
  // 누적 통계(총 거리/완주 횟수) - 목록과 별개 엔드포인트라 별도 state로 관리. 더보기를
  // 여러 번 눌러도 이 값은 안 바뀌므로 목록 fetch 로직에 묶지 않고 마운트 시 한 번만 받는다.
  const [stats, setStats] = useState(null);
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
  // DELETE는 성공했는데 그 뒤 reloadRecords()가 실패하면, 서버에는 이미 없는 기록이
  // 화면엔 그대로 남고 삭제 버튼도 다시 눌리는 상태가 된다 - 다시 누르면 404만 반복돼서
  // 혼란스럽다(리뷰 지적). 이런 기록들을 표시해서 재시도 대신 새로고침을 유도한다.
  const [staleRecordIds, setStaleRecordIds] = useState(() => new Set());
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
  // "다음 더보기가 요청할 서버 페이지"를 화면에 남은 고유 항목 수(recordsRef.current.length)
  // 로 역산하면 안 된다 - 다른 탭의 변경으로 응답의 항목이 기존 목록과 전부(또는 일부)
  // 중복돼 dedup으로 걸러지면, 고유 항목 수가 늘지 않아 같은 페이지를 반복 요청하게 된다
  // (리뷰 지적). 실제로 요청에 성공한 서버 페이지 번호를 이 ref에 직접 기록해서, 항목 수와
  // 무관하게 "다음엔 몇 페이지를 요청해야 하는지"를 별도로 관리한다.
  const lastFetchedPageRef = useRef(0);

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
      // 이 요청이 실제로 요청한 페이지(targetPage) 번호를 그대로 기록한다 - 응답 항목이
      // 기존 목록과 겹쳐 dedup으로 전부/일부 걸러져도, "이 페이지는 이미 조회했다"는 사실은
      // 변하지 않으므로 항목 수가 아니라 targetPage 자체를 신뢰한다(리뷰 지적)
      lastFetchedPageRef.current = targetPage;
      // append(더보기)는 다음 페이지만 새로 받아올 뿐, 이미 화면에 있던(그중 "새로고침
      // 필요" 상태인 유령 기록 포함) 항목은 이 요청으로 전혀 재확인되지 않는다 - 여기서
      // 지우면 재검증 없이 방어가 풀려버린다(리뷰 지적). 전체를 새로 받아오는 첫 페이지
      // 조회일 때만, 서버와 다시 동기화됐다고 보고 지운다
      if (!append) {
        setStaleRecordIds(new Set());
      }
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
    fetchStats();
    return () => {
      unmountedRef.current = true;
    };
  }, [userLoading, user]);

  // 누적 통계는 목록과 별개 엔드포인트라 실패해도 목록 자체엔 영향 없게 조용히 무시한다
  // (요약 정보일 뿐이지 핵심 기능이 아니므로 에러 UI를 따로 두지 않는다)
  // unmountedRef만으로는 요청 순서를 구분 못한다 - 마운트 시 조회가 지연되는 동안 삭제
  // 후 재조회가 먼저 끝나버리면, 나중에 도착한 마운트 시점 응답(오래된 수치)이 최신 응답을
  // 덮어쓸 수 있다(리뷰 지적). requestRecordsRef 등과 동일한 패턴으로 요청 번호를 매겨
  // 가장 최근 요청의 응답만 반영한다.
  const statsRequestIdRef = useRef(0);
  const fetchStats = async () => {
    const requestId = ++statsRequestIdRef.current;
    const isStale = () => unmountedRef.current || statsRequestIdRef.current !== requestId;
    try {
      const res = await apiFetch('/v1/records/stats');
      if (isStale() || !res.ok) return;
      const data = await res.json();
      if (isStale()) return;
      setStats(data);
    } catch {
      // 통계 조회 실패는 조용히 무시
    }
  };

  const handleLoadMore = () => {
    if (loadingMoreRef.current) return;
    // 목록에 "새로고침 필요"(재조회 실패로 서버와 어긋난) 기록이 남아있으면 더보기를
    // 막는다 - 더보기는 기존 목록을 재검증하지 않고 다음 페이지만 이어붙이므로, 어긋난
    // 상태 위에서 진행하면 삭제로 밀린 offset 때문에 기록이 하나 조용히 누락될 수 있다
    // (리뷰 지적). 전체 재조회(reloadRecords)가 성공해서 staleRecordIds가 비워질 때까지
    // 기다려야 한다.
    if (staleRecordIds.size > 0) return;
    loadingMoreRef.current = true;
    // 큐에서 대기하는 동안(삭제 후 재조회가 앞에 있는 경우)에도 버튼이 바로 비활성화되고
    // "불러오는 중..."으로 보이도록, fetchRecords가 실제로 시작되기 전에 미리 켜둔다
    setLoadingMore(true);
    setLoadMoreError('');
    // page(state)나 화면 항목 수를 클릭 시점에 미리 캡처해서 넘기지 않는다 - 앞에 대기
    // 중인 reloadRecords가 먼저 끝나면 그 사이 값이 달라진다. lastFetchedPageRef는 실제로
    // 요청에 성공한 서버 페이지 번호만 담고 있어 화면 항목 수(dedup으로 줄어들 수 있는
    // 값)와 무관하게 신뢰할 수 있다(리뷰 지적) - 실행 시점(큐 대기 후)에 읽는다.
    runListOpExclusive(() => fetchRecords(lastFetchedPageRef.current + 1, { append: true }));
  };

  // 삭제 후 재조회 전용 - fetchRecords(1)을 그대로 쓰면 loading을 true로 바꿔 목록이
  // 잠깐 사라진다. MyCourses.jsx(usePaginatedCourses.reload)와 동일하게 loading은
  // 건드리지 않는다. 예전엔 지금까지 불러온 개수만큼 size를 한 번에 늘려서 요청했는데,
  // 백엔드가 size<=100으로 막아놔서 100개 넘게 불러온 뒤 삭제하면 목록이 100개로
  // 잘리면서 다음 "더보기"가 잘려나간 구간을 건너뛰는 문제가 있었다(리뷰 지적). 매
  // 요청을 더보기와 똑같은 size(20)로 나눠서 필요한 페이지 수만큼 조회한다 - 다음
  // 더보기는 lastFetchedPageRef(실제로 요청한 페이지 번호) 기준으로 위치를 계산하므로
  // (handleLoadMore 참고) 여기서도 pagesToRefetch를 그대로 기록해두기만 하면 된다. 순차
  // (await 체인)로 하면 페이지 수만큼 왕복시간이 쌓여 기록이 많은 유저일수록 삭제할 때
  // 체감 지연이 길어지므로(리뷰 지적) 병렬로 요청한다.
  const reloadRecords = () =>
    runListOpExclusive(async () => {
      const requestId = ++requestIdRef.current;
      const isStale = () => unmountedRef.current || requestIdRef.current !== requestId;
      // recordsRef.current.length(고유 항목 수)가 아니라 lastFetchedPageRef(실제로 요청
      // 성공한 페이지 수)를 기준으로 삼는다 - 다른 탭에서 새 기록이 여러 번 생겨 더보기로
      // 불러온 페이지들 사이에 중복이 섞이면 고유 항목 수가 실제 요청 페이지 수보다 작아질
      // 수 있고, 그러면 필요한 것보다 적은 페이지만 재조회해서 삭제 직후 화면에 있던
      // 기록이 순간적으로 사라지는 문제가 생긴다(리뷰 지적) - handleLoadMore와 동일한 이유
      const pagesToRefetch = Math.max(lastFetchedPageRef.current, 1);
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
        // pagesToRefetch개 페이지를 실제로 다 요청했으므로, 그 개수와 무관하게(dedup으로
        // 고유 항목이 줄었어도) 다음 더보기는 그 다음 페이지부터 시작해야 한다(리뷰 지적)
        lastFetchedPageRef.current = pagesToRefetch;
        setStaleRecordIds(new Set());
        setTotal(latestTotal);
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
        // 다른 탭/기기에서 이미 이 기록을 지웠으면 404가 온다 - "이 PR 전체의 동기"인
        // 다른 탭과의 충돌 시나리오에서 오히려 흔하게 생길 수 있는 경우라, 이미 삭제된
        // 것으로 간주해 staleRecordIds에 추가한다(재시도해도 404만 반복되는 걸 막음).
        // 진행 중인 기록 삭제 시도(409)는 이유가 명확하니 구분해서 보여준다(리뷰 지적)
        if (res.status === 404) {
          setDeleteError('이미 삭제된 기록이에요. 목록을 새로고침 해주세요.');
          setStaleRecordIds((prev) => new Set(prev).add(recordId));
          return;
        }
        const message =
          res.status === 409 ? '진행 중인 기록은 삭제할 수 없어요.' : '삭제에 실패했어요.';
        setDeleteError(message);
        return;
      }
      const reloaded = await reloadRecords();
      if (!reloaded) {
        setDeleteError('삭제는 됐지만 목록을 새로고침하지 못했어요. 새로고침 해주세요.');
        // 서버에는 이미 없는 기록이 화면엔 남아있는 상태다 - 삭제 버튼을 다시 활성화하면
        // 재시도해도 404만 반복되니, 새로고침 전까지는 비활성 상태를 유지한다(리뷰 지적)
        setStaleRecordIds((prev) => new Set(prev).add(recordId));
      }
      // 완주(is_completed=true) 기록을 지웠으면 누적 통계도 줄어들어야 한다 - 삭제된
      // 기록이 완주였는지 여기서 구분하지 않고 항상 다시 받아온다(실패해도 조용히 무시됨)
      fetchStats();
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

        {/* 완주 기록 기준 누적 통계 - 실패해도 목록 자체엔 영향 없어야 하므로 stats가
            아직 없을 땐(로딩 중이거나 실패) 그냥 아무것도 안 보여준다 */}
        {stats && (
          <div className="record-history-stats-summary">
            <span>누적 거리 {stats.total_distance_km.toFixed(1)}km</span>
            <span>완주 {stats.total_completions}회</span>
          </div>
        )}

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
                    disabled={deletingIds.has(record.record_id) || staleRecordIds.has(record.record_id)}
                  >
                    {deletingIds.has(record.record_id)
                      ? '삭제 중...'
                      : staleRecordIds.has(record.record_id)
                        ? '새로고침 필요'
                        : '삭제'}
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
            disabled={loadingMore || staleRecordIds.size > 0}
          >
            {loadingMore
              ? '불러오는 중...'
              : staleRecordIds.size > 0
                ? '새로고침 필요'
                : '기록 더보기'}
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
