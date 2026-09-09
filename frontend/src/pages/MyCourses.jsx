import { useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../api';
import CourseCard from '../components/CourseCard';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { usePaginatedCourses } from '../hooks/usePaginatedCourses';
import { formatCustomSigunBadge } from '../utils/format';

const PAGE_SIZE = 20;

const MyCourses = () => {
  const { user, isLoading: userLoading } = useUser();

  // user 아직 없으면 path를 null로 둬서 훅이 조회를 미룸 ("불러오는 중..." 유지)
  const path = user ? '/v1/courses/custom' : null;
  const buildQuery = (targetPage, size = PAGE_SIZE) =>
    `created_by=${user.user_id}&page=${targetPage}&size=${size}`;

  const { courses, total, loading, loadingMore, error, loadMoreError, loadMore, reload } =
    usePaginatedCourses(path, buildQuery, [user?.user_id]);

  // 목록 조회 실패 'error'와 분리된 'deleteError' state 새로 만듦.
  // ㅡ 코스 삭제 실패 시 기존 목록 전체가 숨겨지지 않도록: 독립된 state로 관리
  const [deleteError, setDeleteError] = useState('');
  const [deletingId, setDeletingId] = useState(null); // 삭제 진행 중인 코스 id — 버튼 중복 클릭 방지

  const handleDelete = async (courseId) => {
    if (!window.confirm('정말 이 코스를 삭제하시겠어요?')) return;
    setDeleteError('');
    setDeletingId(courseId);
    try {
      const res = await apiFetch(`/v1/courses/custom/${courseId}`, { method: 'DELETE' });
      if (!res.ok) {
        setDeleteError('삭제에 실패했어요');
        return;
      }
      // 로컬에서 항목만 지우면 이후 "더보기"가 요청하는 offset이 한 칸씩 밀려서 누락
      // — 삭제 성공 후엔 항상 서버에서 다시 받아와 통째로 교체
      const reloaded = await reload();
      if (!reloaded) {
        setDeleteError('삭제는 됐지만 목록을 새로고침하지 못했어요. 새로고침 해주세요.');
      }
    } catch (err) {
      console.error('내 코스 삭제 실패:', err);
      setDeleteError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setDeletingId(null);
    }
  };

  if (!userLoading && !user) {
    return (
      <>
        <Header />
        <main className="course-list-page">
          <p className="course-list-status error">로그인 후 이용할 수 있어요.</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="course-list-page">
        <div className="section-heading">
          <div>
            <span className="section-kicker">나만의 코스</span>
            <h2>내가 만든 코스</h2>
          </div>
          <Link to="/courses/custom/new" className="primary-button">
            코스 만들기
          </Link>
        </div>

        {loading && <p className="course-list-status">불러오는 중...</p>}
        {error && <p className="course-list-status error">{error}</p>}
        {/* 목록 조회 에러(error)와 분리 — 삭제 실패가 이미 불러온 목록을 숨기면 안 됨 */}
        {deleteError && <p className="course-list-status error">{deleteError}</p>}

        {!loading && !error && courses.length === 0 && (
          <p className="course-list-status">아직 만든 코스가 없어요.</p>
        )}

        {!loading && !error && courses.length > 0 && (
          <div className="course-grid">
            {courses.map((course) => (
              <CourseCard
                key={course.course_id}
                course={course}
                to={`/courses/custom/${course.course_id}`}
                badgeText={formatCustomSigunBadge(course)}
                actions={
                  <>
                    <Link
                      to={`/courses/custom/${course.course_id}/edit`}
                      className="course-card-edit"
                    >
                      수정
                    </Link>
                    <button
                      type="button"
                      className="course-card-delete"
                      onClick={() => handleDelete(course.course_id)}
                      disabled={deletingId === course.course_id}
                    >
                      {deletingId === course.course_id ? '삭제 중...' : '삭제'}
                    </button>
                  </>
                }
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
      </main>
    </>
  );
};

export default MyCourses;
