import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import useFocusTrap from '../hooks/useFocusTrap';
import { DIFFICULTY_COLOR, DIFFICULTY_LABEL } from '../utils/difficulty';

// 백엔드 검증 규칙과 동일 (app/config.py) — 서버가 최종 검증하고, 여긴 UX용 사전 안내
const NICKNAME_PATTERN = '[가-힣a-zA-Z0-9]{2,10}';
const LOCATION_PATTERN = '[가-힣a-zA-Z0-9\\s]{1,50}';
const PROFILE_IMAGE_MAX_SIZE_MB = 2;
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
// CourseDetail.jsx의 리뷰 목록과 동일한 페이지 크기 (백엔드 기본값도 20)
const REVIEW_PAGE_SIZE = 20;

const MyPage = () => {
  const navigate = useNavigate();
  const imageModalRef = useRef(null);
  const reviewModalRef = useRef(null);
  const { user, setUser, isLoading, hasError, refreshUser } = useUser();

  const [nickname, setNickname] = useState('');
  const [location, setLocation] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingImage, setDeletingImage] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [isImageOpen, setIsImageOpen] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);

  const [myReviews, setMyReviews] = useState([]);
  // 모달을 열기 전엔 로딩 상태가 아니므로 초기값은 false (RecordHistory.jsx와 다른 부분)
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState('');
  const [reviewsTotal, setReviewsTotal] = useState(0);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);
  const [loadMoreReviewsError, setLoadMoreReviewsError] = useState('');
  // 삭제 진행 중인 리뷰 id들 - RecordHistory.jsx의 deletingIds와 동일하게 Set으로 둬서
  // 여러 리뷰를 연달아 삭제해도 각자 독립적으로 버튼 비활성화 상태를 관리한다.
  const [deletingReviewIds, setDeletingReviewIds] = useState(() => new Set());
  const [reviewDeleteError, setReviewDeleteError] = useState('');
  // DELETE는 성공했는데 그 뒤 reloadMyReviews()가 실패하면, 서버에는 이미 없는 리뷰가
  // 화면엔 그대로 남고 삭제 버튼도 다시 눌리는 상태가 된다 - RecordHistory.jsx의
  // staleRecordIds와 동일한 이유로 이런 리뷰를 표시해서 재시도 대신 새로고침을 유도한다.
  const [staleReviewIds, setStaleReviewIds] = useState(() => new Set());
  // 화면에 렌더링되지 않는 값이라 state 대신 ref로 둔다 (불필요한 리렌더 방지)
  const reviewsPageRef = useRef(1);
  // reloadMyReviews가 삭제 직후(setMyReviews 반영 전) 최신 개수를 동기적으로 읽을 수
  // 있도록 미러링한다 - RecordHistory.jsx의 recordsRef와 동일한 이유(setRecords의
  // updater는 렌더링 단계에서 나중에 실행되므로, 호출하는 자리에서 직접 갱신해야 한다)
  const myReviewsRef = useRef(myReviews);
  // 모달이 닫힌 뒤 도착하는 응답이 setState를 시도하지 않도록 막는다
  const reviewsUnmountedRef = useRef(false);
  // 모달을 여러 번 열고 닫을 때, 먼저 시작된 요청의 응답이 늦게 도착해도 최신 요청만 반영한다
  const reviewsRequestIdRef = useRef(0);
  // loadingMoreReviews(state)는 리렌더 전까지 반영되지 않아, "더보기" 버튼이 disabled
  // 되기 전에 연달아 클릭되면 중복 요청이 나갈 수 있다 - ref로 클릭 시점에 즉시 막는다
  const loadingMoreReviewsRef = useRef(false);
  // 더보기(fetchMyReviews append)와 삭제 후 재조회(reloadMyReviews)는 둘 다 myReviews를
  // 직접 교체·병합한다 - 동시에 실행되면 reviewsRequestIdRef 하나로는 늦게 시작한 쪽이
  // 먼저 시작한 쪽을 무조건 stale 처리해버려서, 더보기 버튼이 영영 안 풀리는 문제가 생긴다
  // (리뷰 지적). RecordHistory.jsx와 동일하게 큐에 넣어 항상 하나씩 순서대로만 실행한다.
  const listOpQueueRef = useRef(Promise.resolve());
  const runListOpExclusive = (op) => {
    const run = listOpQueueRef.current.then(op, op);
    listOpQueueRef.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  };

  // 모달을 열 때마다 이전 세션의 리뷰 목록 상태를 처음으로 되돌린다
  const resetReviewsState = () => {
    setLoadingMoreReviews(false);
    loadingMoreReviewsRef.current = false;
    setLoadMoreReviewsError('');
    setReviewDeleteError('');
    setDeletingReviewIds(new Set());
    setStaleReviewIds(new Set());
    setMyReviews([]);
    myReviewsRef.current = [];
    setReviewsTotal(0);
    reviewsPageRef.current = 1;
  };

  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(() => setMessage(''), 5000);
    return () => clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    if (!isImageOpen && !isReviewOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsImageOpen(false);
        setIsReviewOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isImageOpen, isReviewOpen]);

  useEffect(() => {
    // hasError면 일시적인 조회 실패일 뿐 진짜 로그아웃이 아니므로 로그인 화면으로 보내지 않음
    if (!isLoading && !user && !hasError) {
      navigate('/login', { replace: true });
    }
  }, [isLoading, user, hasError, navigate]);

  useEffect(() => {
    if (user) {
      setNickname(user.nickname || '');
      setLocation(user.location || '');
    }
    // profile_image_url만 바뀌었을 때(사진 업로드)는 재실행 안 되도록 닉네임/거주지 값만 의존성으로 좁힘
    // — 그렇지 않으면 사진 업로드 시 입력 중이던 닉네임/거주지가 서버 값으로 덮어써짐
  }, [user?.nickname, user?.location]);

  useFocusTrap(imageModalRef, isImageOpen);
  useFocusTrap(reviewModalRef, isReviewOpen);

  const fetchMyReviews = async (targetPage = 1, { append = false } = {}) => {
    if (append) {
      if (loadingMoreReviewsRef.current) return;
      loadingMoreReviewsRef.current = true;
    }
    const requestId = ++reviewsRequestIdRef.current;
    const isStale = () => reviewsUnmountedRef.current || reviewsRequestIdRef.current !== requestId;

    const setLoading = append ? setLoadingMoreReviews : setReviewsLoading;
    const setError = append ? setLoadMoreReviewsError : setReviewsError;

    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`/v1/reviews/mine?page=${targetPage}&size=${REVIEW_PAGE_SIZE}`);
      if (isStale()) return;
      if (!res.ok) {
        const errorMessage =
          res.status === 401
            ? '로그인이 필요해요.'
            : append
              ? '리뷰를 더 불러오지 못했어요.'
              : '리뷰를 불러오지 못했어요.';
        setError(errorMessage);
        return;
      }
      const data = await res.json();
      if (isStale()) return;
      // myReviewsRef.current를 prev로 쓴다 - setMyReviews(updaterFn)의 updater는 렌더링
      // 단계에서 나중에 실행되므로, 여기서 곧바로 동기적으로 반영해야 삭제 직후 이어지는
      // reloadMyReviews가 최신 개수를 즉시 읽을 수 있다(RecordHistory.jsx와 동일한 이유)
      let next = data.items;
      if (append) {
        // page 기반 페이지네이션은 그 사이 리뷰가 삭제되면 경계에서 겹칠 수 있다 -
        // review_id 기준으로 걸러서 중복 렌더링을 막는다
        const existingIds = new Set(myReviewsRef.current.map((r) => r.review_id));
        next = [...myReviewsRef.current, ...data.items.filter((r) => !existingIds.has(r.review_id))];
      }
      myReviewsRef.current = next;
      setMyReviews(next);
      reviewsPageRef.current = data.page;
      setReviewsTotal(data.total);
    } catch {
      if (!isStale()) {
        setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      }
    } finally {
      // 이 요청이 stale해진 뒤에 늦게 끝나면 ref를 여기서 풀지 않는다 - stale해진 시점에
      // resetReviewsState가 이미 리셋했고, 그 이후 시작된 요청이 아직 진행 중일 수 있는데
      // 여기서 무조건 풀면 그 진행 중인 요청의 중복 클릭 방지가 풀려버린다(리뷰 지적)
      if (append && !isStale()) loadingMoreReviewsRef.current = false;
      // 로딩 플래그는 이 요청 자신이 최신일 때만 끈다 - 모달이 닫혔다 다시 열려서 stale해진
      // 경우엔 위 resetReviewsState가 명시적으로 리셋해주므로 여기서 무조건 꺼줄 필요가 없다
      if (!isStale()) setLoading(false);
    }
  };

  useEffect(() => {
    if (!isReviewOpen) return undefined;
    // StrictMode(개발 모드)가 effect를 마운트→클린업→마운트 순으로 두 번 실행하므로,
    // 매 실행 시작 시점에 반드시 false로 되돌려야 두 번째 실행의 응답이 무시되지 않는다
    reviewsUnmountedRef.current = false;
    // 이전에 열었을 때 남은 상태를 초기화한다 - 코스 상세에서 리뷰를 수정/삭제하고
    // 돌아왔을 수 있으므로 열 때마다 처음부터 다시 불러온다
    resetReviewsState();
    fetchMyReviews(1);
    return () => {
      reviewsUnmountedRef.current = true;
    };
  }, [isReviewOpen]);

  const handleLoadMoreReviews = () => {
    // 목록에 "새로고침 필요"(재조회 실패로 서버와 어긋난) 리뷰가 남아있으면 더보기를
    // 막는다 - RecordHistory.jsx와 동일한 이유(더보기는 기존 목록을 재검증하지 않고
    // 다음 페이지만 이어붙이므로, 어긋난 상태 위에서 진행하면 리뷰가 하나 조용히
    // 누락될 수 있다)
    if (staleReviewIds.size > 0) return;
    runListOpExclusive(() => fetchMyReviews(reviewsPageRef.current + 1, { append: true }));
  };

  // 리뷰 삭제 후 전용 재조회 - RecordHistory.jsx의 reloadRecords와 동일한 이유로 로컬에서
  // 항목만 지우지 않는다: 그러면 이후 "더보기"가 요청하는 offset이 한 칸씩 밀려서 다른
  // 리뷰가 누락될 수 있다. 백엔드 size 상한(le=100)을 넘지 않게 더보기와 같은 size(20)로
  // 나눠서 지금까지 불러온 만큼 다시 병렬 조회한다.
  const reloadMyReviews = () =>
    runListOpExclusive(async () => {
      const requestId = ++reviewsRequestIdRef.current;
      const isStale = () =>
        reviewsUnmountedRef.current || reviewsRequestIdRef.current !== requestId;
      // myReviewsRef.current.length(고유 항목 수)가 아니라 reviewsPageRef(실제로 요청
      // 성공한 페이지 수)를 기준으로 삼는다 - RecordHistory.jsx의 reloadRecords와 동일한
      // 이유(리뷰 지적): 더보기로 불러온 페이지들 사이에 중복이 섞이면 고유 항목 수가
      // 실제 요청 페이지 수보다 작아질 수 있고, 그러면 필요한 것보다 적은 페이지만
      // 재조회해서 삭제 직후 화면에 있던 리뷰가 순간적으로 사라지는 문제가 생긴다
      const pagesToRefetch = Math.max(reviewsPageRef.current, 1);
      try {
        const responses = await Promise.all(
          Array.from({ length: pagesToRefetch }, (_, i) =>
            apiFetch(`/v1/reviews/mine?page=${i + 1}&size=${REVIEW_PAGE_SIZE}`),
          ),
        );
        if (isStale()) return true;
        if (responses.some((res) => !res.ok)) return false;
        const datas = await Promise.all(responses.map((res) => res.json()));
        if (isStale()) return true;

        const collectedIds = new Set();
        const collected = [];
        for (const data of datas) {
          for (const review of data.items) {
            if (collectedIds.has(review.review_id)) continue;
            collectedIds.add(review.review_id);
            collected.push(review);
          }
        }
        const latestTotal = datas.at(-1)?.total ?? 0;

        myReviewsRef.current = collected;
        setMyReviews(collected);
        setStaleReviewIds(new Set());
        setReviewsTotal(latestTotal);
        reviewsPageRef.current = pagesToRefetch;
        return true;
      } catch {
        return isStale();
      }
    });

  const handleDeleteReview = async (reviewId) => {
    if (!window.confirm('정말 이 리뷰를 삭제하시겠어요?')) return;
    setReviewDeleteError('');
    setDeletingReviewIds((prev) => new Set(prev).add(reviewId));
    try {
      const res = await apiFetch(`/v1/reviews/${reviewId}`, { method: 'DELETE' });
      if (!res.ok) {
        // 다른 곳에서 이미 이 리뷰를 지웠으면 404가 온다 - RecordHistory.jsx와 동일하게
        // 이미 삭제된 것으로 간주해 staleReviewIds에 추가한다(재시도해도 404만 반복되는
        // 걸 막음, 리뷰 지적)
        if (res.status === 404) {
          setReviewDeleteError('이미 삭제된 리뷰예요. 목록을 새로고침 해주세요.');
          setStaleReviewIds((prev) => new Set(prev).add(reviewId));
          return;
        }
        setReviewDeleteError('리뷰 삭제에 실패했어요.');
        return;
      }
      const reloaded = await reloadMyReviews();
      if (!reloaded) {
        setReviewDeleteError(
          '삭제는 됐지만 목록을 새로고침하지 못했어요. 모달을 닫았다가 다시 열어주세요.',
        );
        // 서버에는 이미 없는 리뷰가 화면엔 남아있는 상태다 - 삭제 버튼을 다시 활성화하면
        // 재시도해도 404만 반복되니, 재조회가 성공할 때까지 비활성 상태를 유지한다
        setStaleReviewIds((prev) => new Set(prev).add(reviewId));
      }
    } catch {
      setReviewDeleteError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setDeletingReviewIds((prev) => {
        const next = new Set(prev);
        next.delete(reviewId);
        return next;
      });
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setMessage('');
    setSaving(true);

    try {
      const res = await apiFetch('/v1/users/me', {
        method: 'PATCH',
        body: JSON.stringify({ nickname, location }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '수정 중 오류가 발생했어요');
        return;
      }

      setUser(await res.json());
      setMessage('저장됐어요');
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setSaving(false);
    }
  };

  const handleImageChange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    setError('');

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setError('지원하지 않는 이미지 형식입니다 (jpg, png, webp만 가능)');
      event.target.value = '';
      return;
    }

    if (file.size > PROFILE_IMAGE_MAX_SIZE_MB * 1024 * 1024) {
      setError(`이미지 크기는 최대 ${PROFILE_IMAGE_MAX_SIZE_MB}MB까지 업로드 가능합니다`);
      event.target.value = '';
      return;
    }

    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await apiFetch('/v1/users/me/image', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '이미지 업로드에 실패했어요');
        return;
      }

      const data = await res.json();
      setUser((prev) => ({ ...prev, profile_image_url: data.profile_image_url }));
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      event.target.value = '';
      setUploading(false);
    }
  };

  const handleImageDelete = async () => {
    setError('');
    setDeletingImage(true);

    try {
      const res = await apiFetch('/v1/users/me/image', { method: 'DELETE' });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '이미지 삭제에 실패했어요');
        return;
      }

      setUser((prev) => ({ ...prev, profile_image_url: null }));
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setDeletingImage(false);
    }
  };

  return (
    <>
      <Header />
      <main className="mypage-page">
        <h1>마이페이지</h1>

        {isLoading && <p>불러오는 중...</p>}
        {!isLoading && !user && hasError && (
          <p>
            일시적인 오류로 정보를 불러오지 못했어요.{' '}
            <button type="button" className="text-button" onClick={() => refreshUser()}>
              다시 시도
            </button>
          </p>
        )}
        {!isLoading && !user && !hasError && <p>정보를 불러오지 못했어요.</p>}

        {user && (
          <>
            <div className="mypage-profile">
              {user.profile_image_url ? (
                <button
                  type="button"
                  className="profile-avatar large"
                  onClick={() => setIsImageOpen(true)}
                  aria-label="프로필 사진 원본 보기"
                >
                  <img src={user.profile_image_url} alt="" />
                </button>
              ) : (
                <div className="profile-avatar large" aria-hidden="true">
                  <img src="/assets/default-avatar.png" alt="" />
                </div>
              )}
              <div className="mypage-image-actions">
                <label className="mypage-image-upload">
                  {uploading ? '업로드 중...' : '프로필 사진 변경'}
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    onChange={handleImageChange}
                    disabled={uploading || deletingImage}
                    hidden
                  />
                </label>
                {user.profile_image_url && (
                  <button
                    type="button"
                    className="mypage-image-upload"
                    onClick={handleImageDelete}
                    disabled={uploading || deletingImage}
                  >
                    {deletingImage ? '삭제 중...' : '기본 이미지로 변경'}
                  </button>
                )}
              </div>
            </div>

            <form className="mypage-form" onSubmit={handleSubmit}>
              <label htmlFor="nickname">닉네임</label>
              <input
                id="nickname"
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                placeholder="한글/영문/숫자 2~10자"
                pattern={NICKNAME_PATTERN}
                title="한글/영문/숫자 2~10자로 입력해주세요"
                maxLength={10}
                required
              />

              <label htmlFor="location">거주지</label>
              <input
                id="location"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="예: 강원 속초시"
                pattern={LOCATION_PATTERN}
                title="한글/영문/숫자 1~50자로 입력해주세요"
                maxLength={50}
                required
              />

              {error && <p className="onboarding-error">{error}</p>}
              {message && <p className="mypage-success">{message}</p>}

              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? '저장 중...' : '저장하기'}
              </button>
            </form>

            <button type="button" className="mypage-review-button" onClick={() => setIsReviewOpen(true)}>
              내 리뷰 관리<span>→</span>
            </button>
          </>
        )}
      </main>

      {isImageOpen && user?.profile_image_url && (
        <div
          ref={imageModalRef}
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="프로필 사진 원본"
          onClick={() => setIsImageOpen(false)}
        >
          <button
            type="button"
            className="modal-close"
            onClick={() => setIsImageOpen(false)}
            aria-label="닫기"
          >
            ×
          </button>
          <img
            className="modal-image"
            src={user.profile_image_url}
            alt="프로필 사진 원본"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      )}

      {isReviewOpen && (
        <div
          ref={reviewModalRef}
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="내가 쓴 리뷰"
          onClick={() => setIsReviewOpen(false)}
        >
          <div className="review-modal-card" onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className="modal-close review-modal-close"
              onClick={() => setIsReviewOpen(false)}
              aria-label="닫기"
            >
              ×
            </button>
            <h2>내가 쓴 리뷰</h2>

            {reviewsLoading && <p className="course-list-status">불러오는 중...</p>}
            {reviewsError && <p className="course-list-status error">{reviewsError}</p>}
            {/* 목록 조회 에러와 분리 - 삭제 실패가 이미 불러온 목록을 숨기면 안 됨 */}
            {reviewDeleteError && <p className="course-list-status error">{reviewDeleteError}</p>}

            {!reviewsLoading && !reviewsError && myReviews.length === 0 && (
              <p className="course-list-status">아직 작성한 리뷰가 없어요.</p>
            )}

            {!reviewsLoading && !reviewsError && myReviews.length > 0 && (
              <ul className="review-list">
                {myReviews.map((review) =>
                  review.course_is_active ? (
                    <li key={review.review_id} className="review-item">
                      {/* 코스가 살아있으면 수정/삭제는 코스 상세에서 하므로 이동 링크만 제공 */}
                      <Link
                        className="text-button"
                        to={`/courses/${review.course_type.toLowerCase()}/${review.course_id}`}
                        onClick={() => setIsReviewOpen(false)}
                      >
                        {review.course_name}
                      </Link>
                      <div className="review-item-header">
                        <span
                          className={`review-difficulty-badge ${DIFFICULTY_COLOR[review.difficulty] ?? ''}`}
                        >
                          {DIFFICULTY_LABEL[review.difficulty]}
                        </span>
                        <span className="record-hint">
                          {new Date(review.created_at).toLocaleDateString('ko-KR')}
                        </span>
                      </div>
                      <p className="review-item-content">{review.content}</p>
                    </li>
                  ) : (
                    <li key={review.review_id} className="review-item">
                      {/* 코스가 삭제(비활성화)되면 코스 상세 API가 404라 그쪽 수정/삭제
                          버튼에 닿을 수 없다 - 여기서 직접 지울 수 있게 한다(리뷰 지적) */}
                      <span className="text-button" aria-disabled="true">
                        {review.course_name} (삭제된 코스)
                      </span>
                      <div className="review-item-header">
                        <span
                          className={`review-difficulty-badge ${DIFFICULTY_COLOR[review.difficulty] ?? ''}`}
                        >
                          {DIFFICULTY_LABEL[review.difficulty]}
                        </span>
                        <span className="record-hint">
                          {new Date(review.created_at).toLocaleDateString('ko-KR')}
                        </span>
                      </div>
                      <p className="review-item-content">{review.content}</p>
                      <button
                        type="button"
                        className="record-history-delete"
                        onClick={() => handleDeleteReview(review.review_id)}
                        disabled={
                          deletingReviewIds.has(review.review_id) ||
                          staleReviewIds.has(review.review_id)
                        }
                      >
                        {deletingReviewIds.has(review.review_id)
                          ? '삭제 중...'
                          : staleReviewIds.has(review.review_id)
                            ? '새로고침 필요'
                            : '삭제'}
                      </button>
                    </li>
                  ),
                )}
              </ul>
            )}

            {loadMoreReviewsError && (
              <p className="course-list-status error">{loadMoreReviewsError}</p>
            )}

            {!reviewsLoading && !reviewsError && myReviews.length < reviewsTotal && (
              <button
                type="button"
                className="text-button review-load-more"
                onClick={handleLoadMoreReviews}
                disabled={loadingMoreReviews || staleReviewIds.size > 0}
              >
                {loadingMoreReviews
                  ? '불러오는 중...'
                  : staleReviewIds.size > 0
                    ? '새로고침 필요'
                    : '리뷰 더보기'}
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
};

export default MyPage;
