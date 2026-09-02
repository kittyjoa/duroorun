import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { DIFFICULTY_COLOR, DIFFICULTY_LABEL } from '../utils/difficulty';

// 백엔드 검증 규칙과 동일 (app/config.py REVIEW_CONTENT_MAX_LENGTH)
const REVIEW_CONTENT_MAX_LENGTH = 2000;
const REVIEW_PAGE_SIZE = 20;

const DifficultyPicker = ({ value, onChange }) => (
  <div className="review-difficulty-picker" role="group" aria-label="체감 난이도">
    {Object.entries(DIFFICULTY_LABEL).map(([level, label]) => (
      <button
        key={level}
        type="button"
        className={value === level ? 'active' : ''}
        onClick={() => onChange(level)}
      >
        {label}
      </button>
    ))}
  </div>
);

const CourseDetail = () => {
  const { courseType, courseId } = useParams();
  const { user } = useUser();
  // 코스를 빠르게 전환하면(같은 컴포넌트가 재사용되며 courseId만 바뀜) 이전 코스의
  // 리뷰 응답이 늦게 도착해 최신 코스의 리뷰를 덮어쓸 수 있다 - 매 렌더마다 최신
  // courseId로 갱신해두고, 응답이 왔을 때 지금도 유효한 요청인지 대조해서 걸러낸다.
  const activeCourseIdRef = useRef(courseId);
  activeCourseIdRef.current = courseId;
  // 코스가 같아도 같은 요청을 여러 번(예: 더보기 도중 코스를 벗어났다 되돌아옴) 보낼 수
  // 있는데, 그중 나중에 시작한 요청보다 먼저 시작한 요청의 응답이 늦게 도착하면 최신
  // 데이터를 덮어쓸 수 있다 - 요청마다 일련번호를 매겨서 가장 최근 요청의 응답만 반영한다.
  const reviewsRequestSeqRef = useRef(0);
  const myReviewRequestSeqRef = useRef(0);
  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [reviews, setReviews] = useState([]);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewsError, setReviewsError] = useState('');
  const [reviewsTotal, setReviewsTotal] = useState(0);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);
  const [reviewActionError, setReviewActionError] = useState('');

  const [reviewContent, setReviewContent] = useState('');
  const [reviewDifficulty, setReviewDifficulty] = useState('NORMAL');
  const [editingReviewId, setEditingReviewId] = useState(null);
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewFormError, setReviewFormError] = useState('');
  const [deletingReviewId, setDeletingReviewId] = useState(null);
  const [uploadingImageReviewId, setUploadingImageReviewId] = useState(null);
  // reviews는 더보기로 불러온 만큼만 담겨있어서, 거기서 내 리뷰를 찾으면 리뷰가 많은
  // 코스에서 내 리뷰가 뒤 페이지로 밀려나 있을 때 오탐(있는데 없다고 판단)이 난다.
  // /reviews/mine으로 별도 확인해서 페이지네이션과 무관하게 정확히 판별한다.
  const [hasMyReview, setHasMyReview] = useState(false);
  // true인 동안은 "내 리뷰 있는지" 확인이 안 끝난 상태 - 이때 작성 폼을 보여주면, 확인이
  // 끝나고 hasMyReview가 true로 바뀌는 순간 폼이 잠깐 떴다 사라지는 깜빡임이 생긴다
  const [checkingMyReview, setCheckingMyReview] = useState(true);
  // 컴포넌트가 언마운트된 뒤 도착하는 리뷰 응답이 setState를 시도하지 않도록 막는다.
  // StrictMode(개발 모드)가 effect를 마운트→클린업→마운트 순으로 두 번 실행하므로,
  // 매 실행 시작 시점에 반드시 false로 되돌려야 두 번째 실행의 응답이 무시되지 않는다
  const unmountedRef = useRef(false);
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
    };
  }, []);

  // fetchReviews/checkMyReview가 공통으로 쓰는 staleness 체크. 호출 시점의 courseId와
  // 일련번호를 캡처해두고, 응답이 왔을 때 그 사이 언마운트/코스 변경/더 최신 요청 발생
  // 중 하나라도 있었으면 true를 반환한다.
  const createStaleChecker = (seqRef) => {
    const requestedCourseId = courseId;
    const requestSeq = ++seqRef.current;
    return () =>
      unmountedRef.current ||
      activeCourseIdRef.current !== requestedCourseId ||
      seqRef.current !== requestSeq;
  };

  useEffect(() => {
    // 이 effect가 재실행된 뒤(= 더 최신 요청이 시작된 뒤) 도착하는 이전 응답은 무시
    let ignore = false;

    const fetchCourse = async () => {
      setLoading(true);
      setError('');
      try {
        const res = await apiFetch(`/v1/courses/${courseType}/${courseId}`);
        if (ignore) return;
        if (!res.ok) {
          if (res.status === 404) {
            setError('코스 정보를 찾을 수 없어요.');
          } else if (res.status === 401 || res.status === 403) {
            setError('이 코스를 볼 권한이 없어요.');
          } else if (res.status >= 500) {
            setError('서버에 문제가 발생했어요. 잠시 후 다시 시도해주세요.');
          } else {
            setError('코스 정보를 불러오지 못했어요.');
          }
          return;
        }
        const data = await res.json();
        setCourse(data);
      } catch {
        if (!ignore) setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    fetchCourse();

    return () => {
      ignore = true;
    };
  }, [courseType, courseId]);

  // "더보기"는 offset(이미 불러온 개수)만큼 건너뛰고 그 다음 항목만 받아서 이어붙인다.
  // 리뷰 수정/삭제/이미지 변경 등 로컬 옵티미스틱 업데이트가 리뷰 목록 순서(생성일 내림차순)
  // 자체는 바꾸지 않으므로 - 작성은 맨 앞에 추가, 삭제는 그 자리에서만 제거 - reviews.length를
  // 그대로 다음 offset으로 써도 서버 쪽 실제 위치와 어긋나지 않는다.
  const fetchReviews = async (offset = 0, { append = false } = {}) => {
    const isStale = createStaleChecker(reviewsRequestSeqRef);

    if (append) {
      setLoadingMoreReviews(true);
    } else {
      setReviewsLoading(true);
    }
    setReviewsError('');
    try {
      const res = await apiFetch(
        `/v1/reviews/courses/${courseId}?offset=${offset}&size=${REVIEW_PAGE_SIZE}`
      );
      if (isStale()) return;
      if (!res.ok) {
        setReviewsError('리뷰를 불러오지 못했어요.');
        return;
      }
      const data = await res.json();
      if (isStale()) return;
      setReviews((prev) => (append ? [...prev, ...data.items] : data.items));
      setReviewsTotal(data.total);
    } catch {
      if (!isStale()) setReviewsError('서버에 연결할 수 없어요.');
    } finally {
      // 로딩 플래그는 staleness와 무관하게 항상 풀어준다 - 여기서도 isStale()로
      // 막으면, 코스를 바꿔서 이 요청이 stale해진 뒤엔 아무도 이 플래그를 되돌려주지
      // 않아 "더보기" 버튼이 다른 코스에서도 계속 disabled로 멈춰버린다.
      if (append) {
        setLoadingMoreReviews(false);
      } else {
        setReviewsLoading(false);
      }
    }
  };

  useEffect(() => {
    fetchReviews(0);
  }, [courseId]);

  const checkMyReview = async () => {
    const isStale = createStaleChecker(myReviewRequestSeqRef);

    if (!user) {
      if (!isStale()) {
        setHasMyReview(false);
        setCheckingMyReview(false);
      }
      return;
    }
    setCheckingMyReview(true);
    try {
      const res = await apiFetch(`/v1/reviews/mine?page=1&size=1&course_id=${courseId}`);
      if (isStale() || !res.ok) return;
      const data = await res.json();
      if (isStale()) return;
      setHasMyReview(data.total > 0);
    } catch {
      // 조용히 무시 - 확인 실패해도 작성 시도 자체는 가능하고, 이미 썼다면 백엔드가 최종 검증함
    } finally {
      if (!isStale()) setCheckingMyReview(false);
    }
  };

  useEffect(() => {
    checkMyReview();
  }, [user, courseId]);

  const handleLoadMoreReviews = () => {
    fetchReviews(reviews.length, { append: true });
  };

  const startEdit = (review) => {
    setEditingReviewId(review.review_id);
    setReviewContent(review.content);
    setReviewDifficulty(review.difficulty);
    setReviewFormError('');
  };

  const cancelEdit = () => {
    setEditingReviewId(null);
    setReviewContent('');
    setReviewDifficulty('NORMAL');
    setReviewFormError('');
  };

  const handleSubmitReview = async (event) => {
    event.preventDefault();
    const requestedCourseId = courseId;
    setReviewFormError('');
    setReviewSaving(true);
    try {
      const isEditing = editingReviewId != null;
      const url = isEditing ? `/v1/reviews/${editingReviewId}` : `/v1/reviews/courses/${courseId}`;
      const res = await apiFetch(url, {
        method: isEditing ? 'PATCH' : 'POST',
        body: JSON.stringify({ content: reviewContent, difficulty: reviewDifficulty }),
      });
      // 응답을 기다리는 사이 다른 코스로 이동했을 수 있다(같은 컴포넌트가 재사용되므로) -
      // 그러면 지금 보고 있는 코스의 리뷰 상태를 이 응답으로 건드리지 않는다
      if (activeCourseIdRef.current !== requestedCourseId) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewFormError(data?.detail ?? '리뷰 저장에 실패했어요.');
        return;
      }
      const saved = await res.json();
      if (activeCourseIdRef.current !== requestedCourseId) return;
      setReviewContent('');
      setReviewDifficulty('NORMAL');
      setEditingReviewId(null);
      // 로컬에서 목록을 직접 고치므로(fetchReviews를 다시 부르지 않으므로) 초기 로딩 때
      // 뜬 에러 배너가 있었다면 여기서 직접 지워야 한다 - 안 그러면 이번 저장이 성공해도
      // 리뷰가 정상 표시된 목록 위에 옛 에러 문구가 계속 남는다
      setReviewsError('');
      if (isEditing) {
        // 서버 전체를 다시 불러오지 않고, 방금 수정한 리뷰 하나만 바꿔치기한다 - 그래야
        // "더보기"로 펼쳐놓은 나머지 페이지가 리셋되지 않는다
        setReviews((prev) => prev.map((r) => (r.review_id === saved.review_id ? saved : r)));
      } else {
        // 새 리뷰는 최신순 목록 맨 앞에 추가한다
        setReviews((prev) => [saved, ...prev]);
        setReviewsTotal((prev) => prev + 1);
      }
      // 작성/수정 성공은 곧 "내 리뷰가 존재함"이므로, 서버에 다시 물어보지 않고 바로 반영한다
      setHasMyReview(true);
    } catch {
      if (activeCourseIdRef.current === requestedCourseId) setReviewFormError('서버에 연결할 수 없어요.');
    } finally {
      setReviewSaving(false);
    }
  };

  const handleDeleteReview = async (reviewId) => {
    const requestedCourseId = courseId;
    setReviewActionError('');
    setDeletingReviewId(reviewId);
    try {
      const res = await apiFetch(`/v1/reviews/${reviewId}`, { method: 'DELETE' });
      // 응답을 기다리는 사이 다른 코스로 이동했을 수 있다 - 그 코스의 리뷰 상태를 건드리지 않는다
      if (activeCourseIdRef.current !== requestedCourseId) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '리뷰 삭제에 실패했어요.');
        return;
      }
      setReviewsError('');
      setReviews((prev) => prev.filter((r) => r.review_id !== reviewId));
      setReviewsTotal((prev) => Math.max(0, prev - 1));
      // 코스당 리뷰 1개 제한이라, 삭제 성공은 곧 "내 리뷰가 더 이상 없음"이므로 바로 반영한다
      setHasMyReview(false);
    } catch {
      if (activeCourseIdRef.current === requestedCourseId) setReviewActionError('서버에 연결할 수 없어요.');
    } finally {
      setDeletingReviewId(null);
    }
  };

  const handleUploadImage = async (reviewId, event) => {
    const file = event.target.files[0];
    if (!file) return;
    const requestedCourseId = courseId;
    setReviewActionError('');
    setUploadingImageReviewId(reviewId);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiFetch(`/v1/reviews/${reviewId}/images`, {
        method: 'POST',
        body: formData,
      });
      // 업로드 도중 다른 코스로 이동했을 수 있다 - 그 코스의 리뷰 목록을 건드리지 않는다
      if (activeCourseIdRef.current !== requestedCourseId) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '이미지 업로드에 실패했어요.');
        return;
      }
      const saved = await res.json();
      if (activeCourseIdRef.current !== requestedCourseId) return;
      // 이미지가 반영된 리뷰 전체(images 포함)를 그대로 받아서 그 항목만 바꿔치기한다
      setReviews((prev) => prev.map((r) => (r.review_id === saved.review_id ? saved : r)));
    } catch {
      if (activeCourseIdRef.current === requestedCourseId) setReviewActionError('서버에 연결할 수 없어요.');
    } finally {
      event.target.value = '';
      setUploadingImageReviewId(null);
    }
  };

  const handleDeleteImage = async (reviewId, imageId) => {
    const requestedCourseId = courseId;
    setReviewActionError('');
    try {
      const res = await apiFetch(`/v1/reviews/${reviewId}/images/${imageId}`, {
        method: 'DELETE',
      });
      // 삭제 도중 다른 코스로 이동했을 수 있다 - 그 코스의 리뷰 목록을 건드리지 않는다
      if (activeCourseIdRef.current !== requestedCourseId) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '이미지 삭제에 실패했어요.');
        return;
      }
      // 204라 응답 본문이 없으므로, 해당 리뷰의 이미지 목록에서 그 이미지만 로컬에서 제거한다
      setReviews((prev) =>
        prev.map((r) =>
          r.review_id === reviewId
            ? { ...r, images: r.images.filter((img) => img.image_id !== imageId) }
            : r
        )
      );
    } catch {
      if (activeCourseIdRef.current === requestedCourseId) setReviewActionError('서버에 연결할 수 없어요.');
    }
  };

  if (loading) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status">불러오는 중...</p>
        </main>
      </>
    );
  }

  if (error || !course) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status error">{error || '코스 정보를 찾을 수 없어요.'}</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="course-detail-page">
        <Link to="/courses" className="text-button">
          ← 목록으로
        </Link>

        <div className="course-detail-heading">
          <span className="section-kicker">
            {courseType === 'drnb' ? (course.sigun ?? course.brd_div) : '커스텀 코스'}
          </span>
          <h1>{course.course_name}</h1>
          {/* 러닝 시작 버튼 */}
          <Link
            to={`/records/start/${courseType}/${courseId}`}
            className="primary-button course-start-run-button"
          >
            러닝 시작
          </Link>
        </div>

        <dl className="course-detail-info">
          <div>
            <dt>난이도</dt>
            <dd>{DIFFICULTY_LABEL[course.difficulty] ?? '정보 없음'}</dd>
          </div>
          <div>
            <dt>평균 체감 난이도</dt>
            <dd>{DIFFICULTY_LABEL[course.average_difficulty] ?? '리뷰 없음'}</dd>
          </div>
          <div>
            <dt>거리</dt>
            <dd>{course.distance != null ? `${course.distance}km` : '정보 없음'}</dd>
          </div>
          <div>
            <dt>예상 소요시간</dt>
            <dd>
              {course.estimated_time != null ? `약 ${course.estimated_time}분` : '정보 없음'}
            </dd>
          </div>
          {courseType === 'drnb' && (
            <div>
              <dt>완주 인증</dt>
              <dd>{course.has_verification_coords ? '가능' : '불가 (좌표 정보 없음)'}</dd>
            </div>
          )}
          {courseType === 'custom' && (
            <div>
              <dt>경유지 수</dt>
              <dd>{course.waypoints?.length ?? 0}개</dd>
            </div>
          )}
        </dl>

        {course.course_description && (
          <p className="course-detail-desc">{course.course_description}</p>
        )}

        {courseType === 'custom' && course.images?.length > 0 && (
          <div className="course-detail-images">
            {course.images.map((image) => (
              <img key={image.image_id} src={image.image_url} alt={course.course_name} />
            ))}
          </div>
        )}

        {course.review_summary && (
          <div className="review-summary-box">
            <h2>AI 리뷰 요약</h2>
            <p>{course.review_summary.summary}</p>
            <span className="record-hint">리뷰 {course.review_summary.review_count}개 기준</span>
          </div>
        )}

        <div className="course-reviews">
          <h2>리뷰</h2>

          {user && !checkingMyReview && !hasMyReview && (
            <form className="review-form" onSubmit={handleSubmitReview}>
              <h3 className="review-form-title">나의 리뷰 작성하기</h3>
              <textarea
                value={reviewContent}
                onChange={(event) => setReviewContent(event.target.value)}
                placeholder="이 코스는 어땠나요? (완주한 코스만 작성 가능해요)"
                maxLength={REVIEW_CONTENT_MAX_LENGTH}
                required
              />
              <label className="review-form-label">체감 난이도</label>
              <DifficultyPicker value={reviewDifficulty} onChange={setReviewDifficulty} />
              {reviewFormError && <p className="onboarding-error">{reviewFormError}</p>}
              <button type="submit" className="primary-button" disabled={reviewSaving}>
                {reviewSaving ? '등록 중...' : '리뷰 등록'}
              </button>
            </form>
          )}

          {reviewsLoading && <p className="course-list-status">리뷰 불러오는 중...</p>}
          {reviewsError && <p className="course-list-status error">{reviewsError}</p>}
          {reviewActionError && <p className="course-list-status error">{reviewActionError}</p>}
          {!reviewsLoading && !reviewsError && reviews.length === 0 && (
            <p className="course-list-status">아직 리뷰가 없어요.</p>
          )}

          {!reviewsLoading && reviews.length > 0 && (
            <ul className="review-list">
              {reviews.map((review) => {
                const isMine = user && review.user_id === user.user_id;
                const isEditingThis = editingReviewId === review.review_id;

                if (isEditingThis) {
                  return (
                    <li key={review.review_id} className="review-item">
                      <form className="review-form" onSubmit={handleSubmitReview}>
                        <textarea
                          value={reviewContent}
                          onChange={(event) => setReviewContent(event.target.value)}
                          maxLength={REVIEW_CONTENT_MAX_LENGTH}
                          required
                        />
                        <label className="review-form-label">체감 난이도</label>
                        <DifficultyPicker value={reviewDifficulty} onChange={setReviewDifficulty} />
                        {reviewFormError && <p className="onboarding-error">{reviewFormError}</p>}
                        <div className="review-item-actions">
                          <button type="submit" className="primary-button" disabled={reviewSaving}>
                            {reviewSaving ? '저장 중...' : '저장'}
                          </button>
                          <button type="button" className="text-button" onClick={cancelEdit}>
                            취소
                          </button>
                        </div>
                      </form>
                    </li>
                  );
                }

                return (
                  <li key={review.review_id} className="review-item">
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

                    {review.images?.length > 0 && (
                      <div className="course-detail-images">
                        {review.images.map((image) => (
                          <div key={image.image_id} className="review-item-image">
                            <img src={image.image_url} alt="리뷰 사진" />
                            {isMine && (
                              <button
                                type="button"
                                aria-label="이미지 삭제"
                                onClick={() => handleDeleteImage(review.review_id, image.image_id)}
                              >
                                ×
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {isMine && (
                      <div className="review-item-actions">
                        <label className="text-button">
                          {uploadingImageReviewId === review.review_id
                            ? '업로드 중...'
                            : '이미지 추가'}
                          <input
                            type="file"
                            accept="image/jpeg,image/png,image/webp,image/gif"
                            hidden
                            onChange={(event) => handleUploadImage(review.review_id, event)}
                            disabled={uploadingImageReviewId === review.review_id}
                          />
                        </label>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => startEdit(review)}
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => handleDeleteReview(review.review_id)}
                          disabled={deletingReviewId === review.review_id}
                        >
                          {deletingReviewId === review.review_id ? '삭제 중...' : '삭제'}
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {!reviewsLoading && reviews.length < reviewsTotal && (
            <button
              type="button"
              className="text-button review-load-more"
              onClick={handleLoadMoreReviews}
              disabled={loadingMoreReviews}
            >
              {loadingMoreReviews ? '불러오는 중...' : '리뷰 더보기'}
            </button>
          )}
        </div>
      </main>
    </>
  );
};

export default CourseDetail;
