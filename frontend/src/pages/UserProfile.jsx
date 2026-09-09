import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import CourseCard from '../components/CourseCard';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { usePaginatedCourses } from '../hooks/usePaginatedCourses';

const PAGE_SIZE = 20;

// 다른 유저의 공개 프로필(닉네임/거주지/만든 코스). 관리자가 보면 강제 탈퇴 버튼도 같이 뜬다.
// 탈퇴한 유저는 백엔드가 애초에 404를 주므로(재가입 차단 정책과 별개로 개인정보 노출 방지),
// 이 페이지에 그런 유저가 뜨는 경우는 없다 — 리뷰/코스 제작자 링크 자체가 탈퇴 시 사라짐.
// 강제 탈퇴 성공 메시지를 보여주는 시간(ms) - 이후 자동으로 관리자 페이지로 이동
const WITHDRAW_REDIRECT_DELAY_MS = 1500;

const UserProfile = () => {
  const { userId } = useParams();
  const { user: viewer } = useUser();
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState('');

  const [reason, setReason] = useState('');
  const [withdrawing, setWithdrawing] = useState(false);
  const [withdrawError, setWithdrawError] = useState('');
  const [withdrawn, setWithdrawn] = useState(false);
  const redirectTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (redirectTimeoutRef.current) clearTimeout(redirectTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      setNotFound(false);
      setError('');
      try {
        const res = await apiFetch(`/v1/users/${userId}`);
        if (cancelled) return;
        if (res.status === 404) {
          setNotFound(true);
          return;
        }
        if (!res.ok) {
          setError('프로필을 불러오지 못했어요.');
          return;
        }
        setProfile(await res.json());
      } catch (err) {
        if (!cancelled) {
          console.error('프로필 조회 실패:', err);
          setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userId]);

  // 프로필 조회가 끝나고 실존하는 유저일 때만 코스 목록을 요청
  const path = !loading && !notFound && !error ? '/v1/courses/custom' : null;
  const buildQuery = (targetPage, size = PAGE_SIZE) =>
    `created_by=${userId}&page=${targetPage}&size=${size}`;
  const {
    courses,
    total,
    loading: coursesLoading,
    loadingMore,
    error: coursesError,
    loadMore,
  } = usePaginatedCourses(path, buildQuery, [userId, loading, notFound, error]);

  const isAdmin = viewer?.user_role === 'ADMIN';
  const isSelf = viewer != null && String(viewer.user_id) === String(userId);
  const canForceWithdraw = isAdmin && !isSelf && profile?.user_role !== 'ADMIN';

  const handleForceWithdraw = async (event) => {
    event.preventDefault();
    if (!reason.trim()) {
      setWithdrawError('사유를 입력해주세요');
      return;
    }
    if (!window.confirm('정말 이 유저를 강제 탈퇴시키겠어요? 되돌릴 수 없어요.')) return;

    setWithdrawing(true);
    setWithdrawError('');
    try {
      const res = await apiFetch(`/v1/admin/users/${userId}`, {
        method: 'DELETE',
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setWithdrawError(data?.detail ?? '강제 탈퇴에 실패했어요');
        return;
      }
      setWithdrawn(true);
      redirectTimeoutRef.current = setTimeout(() => navigate('/admin'), WITHDRAW_REDIRECT_DELAY_MS);
    } catch (err) {
      console.error('강제 탈퇴 실패:', err);
      setWithdrawError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setWithdrawing(false);
    }
  };

  return (
    <>
      <Header />
      <main className="profile-page">
        {loading && <p className="course-list-status">불러오는 중...</p>}
        {!loading && notFound && (
          <p className="course-list-status error">존재하지 않는 사용자예요.</p>
        )}
        {!loading && !notFound && error && <p className="course-list-status error">{error}</p>}

        {!loading && !notFound && !error && profile && (
          <>
            <div className="profile-header">
              <div className="profile-avatar large" aria-hidden="true">
                <img src={profile.profile_image_url || '/assets/default-avatar.png'} alt="" />
              </div>
              <div>
                <h1>{profile.nickname || '이름 없음'}</h1>
                {profile.location && <p className="profile-location">{profile.location}</p>}
              </div>
            </div>

            {canForceWithdraw && (
              <div className="profile-admin-panel">
                {withdrawn ? (
                  <p className="mypage-success">강제 탈퇴 처리됐어요.</p>
                ) : (
                  <form className="profile-admin-form" onSubmit={handleForceWithdraw}>
                    <label htmlFor="force-withdraw-reason">관리자 - 강제 탈퇴 사유</label>
                    <input
                      id="force-withdraw-reason"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="예: 욕설, 부적절한 리뷰 반복 작성"
                      maxLength={255}
                    />
                    {withdrawError && <p className="onboarding-error">{withdrawError}</p>}
                    <button
                      type="submit"
                      className="primary-button danger-button"
                      disabled={withdrawing}
                    >
                      {withdrawing ? '처리 중...' : '강제 탈퇴'}
                    </button>
                  </form>
                )}
              </div>
            )}

            <section className="profile-courses">
              <h2>만든 코스</h2>
              {coursesLoading && <p className="course-list-status">불러오는 중...</p>}
              {coursesError && <p className="course-list-status error">{coursesError}</p>}
              {!coursesLoading && !coursesError && courses.length === 0 && (
                <p className="course-list-status">아직 만든 코스가 없어요.</p>
              )}
              {!coursesLoading && !coursesError && courses.length > 0 && (
                <div className="course-grid">
                  {courses.map((course) => (
                    <CourseCard
                      key={course.course_id}
                      course={course}
                      to={`/courses/custom/${course.course_id}`}
                      badgeText="커스텀 코스"
                    />
                  ))}
                </div>
              )}
              {!coursesLoading && !coursesError && courses.length < total && (
                <div className="course-list-load-more">
                  <button type="button" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? '불러오는 중...' : '더보기'}
                  </button>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
};

export default UserProfile;
