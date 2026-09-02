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
  const requestIdRef = useRef(0);

  useEffect(() => {
    // path 아직 없으면 loading 상태 그대로 둔 채 대기 — 준비되면 deps 변경으로 재실행
    if (!path) return;
    const myRequestId = ++requestIdRef.current;

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
        setCourses(data.items);
        setTotal(data.total);
        setPage(1);
      } catch {
        if (requestIdRef.current === myRequestId) {
          setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
        }
      } finally {
        if (requestIdRef.current === myRequestId) setLoading(false);
      }
    })();
    // buildQuery: 이 페이지 요청하려면 url 뒤에 뭐 붙여야 하는지 만들어줌
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  const loadMore = async () => {
    if (!path) return;
    const myRequestId = ++requestIdRef.current;
    const nextPage = page + 1;
    setLoadingMore(true);
    setError('');
    try {
      const query = buildQuery(nextPage);
      const res = await apiFetch(query ? `${path}?${query}` : path);
      if (requestIdRef.current !== myRequestId) return;
      if (!res.ok) {
        setError('코스 목록을 불러오지 못했어요.');
        return;
      }
      const data = await res.json();
      setCourses((prev) => [...prev, ...data.items]);
      setTotal(data.total);
      setPage(nextPage);
    } catch {
      if (requestIdRef.current === myRequestId) {
        setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      if (requestIdRef.current === myRequestId) setLoadingMore(false);
    }
  };

  // 목록에서 항목 하나를 즉시 제거(삭제 성공 후 반영용) — total도 같이 맞춰서
  // "더보기" 노출 조건(courses.length < total) 정확히 유지되도록
  const removeCourse = (courseId) => {
    setCourses((prev) => prev.filter((c) => c.course_id !== courseId));
    setTotal((prev) => prev - 1);
  };

  return { courses, total, page, loading, loadingMore, error, setError, loadMore, removeCourse };
};
