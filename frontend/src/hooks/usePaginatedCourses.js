import { useEffect, useRef, useState } from 'react';

import { apiFetch } from '../api';

// 전체코스/나만의코스 목록: 공통 더보기 방식 훅.
// - path가 null/undefined면 아무것도 안 함 (예: MyCourses에서 user 로딩 전)
// - 훅 내부에서 requestIdRef로 요청 세대를 관리 (더보기 도중 탭 전환 같은거 버림)
export const usePaginatedCourses = (path, buildQuery, deps) => {
  const [courses, setCourses] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [loadMoreError, setLoadMoreError] = useState('');
  const requestIdRef = useRef(0);

  useEffect(() => {
    // path 아직 없으면 loading 상태 그대로 둔 채 대기 — 준비되면 deps 변경으로 재실행
    if (!path) return undefined;
    const myRequestId = ++requestIdRef.current;
    // 새 1페이지 요청은 진행 중이던 "더보기" 요청을 무효화함
    // ㅡ 새 요청 시작되면 전 요청은 여기서 직접 초기화(finally가 request ID 가드에 막혀서)
    setLoadingMore(false);
    setLoadMoreError('');

    (async () => {
      setLoading(true);
      setError('');
      try {
        const query = buildQuery(1);
        const res = await apiFetch(query ? `${path}?${query}` : path);
        if (requestIdRef.current !== myRequestId) return;
        if (!res.ok) {
          setError('코스 목록을 불러오지 못했어요.');
          return;
        }
        const data = await res.json();
        // res.json()도 비동기라 그 사이에 탭/필터가 바뀌었을 수 있음
        // ㅡ 상태 바꾸기 직전 재확인
        if (requestIdRef.current !== myRequestId) return;
        setCourses(data.items);
        setTotal(data.total);
        setPage(1);
      } catch (err) {
        if (requestIdRef.current === myRequestId) {
          console.error('코스 목록 조회 실패:', err);
          setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
        }
      } finally {
        if (requestIdRef.current === myRequestId) setLoading(false);
      }
    })();

    // path가 null로 바뀌는 경우엔 카운터 못 올리기 때문에
    // 밑의 cleanup 함수 추가해서 카운터 올려서 확실히 무효화시킴.
    // (탭, 필터 변경 후 이전 응답이 목록에 반영되지 않도록)
    return () => {
      requestIdRef.current += 1;
    };
    // buildQuery: 이 페이지 요청하려면 url 뒤에 뭐 붙여야 하는지 만들어줌
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  const loadMore = async () => {
    if (!path) return;
    const myRequestId = ++requestIdRef.current;
    const nextPage = page + 1;
    setLoadingMore(true);
    setLoadMoreError('');
    try {
      const query = buildQuery(nextPage);
      const res = await apiFetch(query ? `${path}?${query}` : path);
      if (requestIdRef.current !== myRequestId) return;
      if (!res.ok) {
        setLoadMoreError('코스 목록을 불러오지 못했어요.');
        return;
      }
      const data = await res.json();
      if (requestIdRef.current !== myRequestId) return;
      setCourses((prev) => [...prev, ...data.items]);
      setTotal(data.total);
      setPage(nextPage);
    } catch (err) {
      if (requestIdRef.current === myRequestId) {
        console.error('코스 더보기 조회 실패:', err);
        setLoadMoreError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      if (requestIdRef.current === myRequestId) setLoadingMore(false);
    }
  };

  // 삭제 등으로 서버 쪽 정렬이 틀어졌을 때 쓰는 전체 재조회.
  // ㅡ 더보기(UI)는 offset 방식 위에서 동작하고 있음.
  // ㅡ 코스 삭제 후 더보기 시 항목 누락될 수 있어서:
  //   예전 로컬 필터링 대신 서버한테 새로 요청하는 방식으로 변경(reload),
  //   page는 그대로 둠(다음 '더보기'가 요청할 위치 계산이 안 어긋나서)
  // ㅡ 성공/실패는 값만 반환하고 에러 메시지는
  //   삭제 자체 실패와 새로고침 실패 구분하기 위해 여기서 안 띄움.
  // ㅡ 예전엔 courses.length만큼(백엔드 size 상한 100으로 캡) 한 번에 재조회했는데,
  //   100개 넘게 불러온 뒤 재조회하면 뒷부분이 캡에 잘리는데 page는 그대로 두다 보니
  //   다음 더보기가 잘린 구간을 건너뛰는 문제가 있었다 (2026-09-09 리뷰 지적). 대신
  //   지금까지 불러온 범위(1~page)를 원래 페이지 크기 그대로 여러 요청으로 복원한다.
  const reload = async () => {
    if (!path) return false;
    const myRequestId = ++requestIdRef.current;
    setLoadingMore(false);
    setLoadMoreError('');
    const pageCount = Math.max(page, 1);
    try {
      const responses = await Promise.all(
        Array.from({ length: pageCount }, (_, i) => {
          const query = buildQuery(i + 1);
          return apiFetch(query ? `${path}?${query}` : path);
        })
      );
      if (requestIdRef.current !== myRequestId) return true; // 그 사이 더 최신 요청이 덮어씀
      if (responses.some((res) => !res.ok)) return false;
      const pages = await Promise.all(responses.map((res) => res.json()));
      if (requestIdRef.current !== myRequestId) return true;
      setCourses(pages.flatMap((data) => data.items));
      setTotal(pages[pages.length - 1].total);
      return true;
    } catch (err) {
      if (requestIdRef.current === myRequestId) {
        console.error('코스 목록 재조회 실패:', err);
      }
      return false;
    }
  };

  return {
    courses,
    total,
    page,
    loading,
    loadingMore,
    error,
    loadMoreError,
    setError,
    loadMore,
    reload,
  };
};
