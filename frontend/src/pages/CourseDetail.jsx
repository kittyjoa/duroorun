import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };
const DIFFICULTY_COLOR = { EASY: 'green', NORMAL: 'blue', HARD: 'red' };
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
  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [reviews, setReviews] = useState([]);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewsError, setReviewsError] = useState('');
  const [reviewsPage, setReviewsPage] = useState(1);
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

  const fetchReviews = async (page = 1, { append = false } = {}) => {
    if (append) {
      setLoadingMoreReviews(true);
    } else {
      setReviewsLoading(true);
    }
    setReviewsError('');
    try {
      const res = await apiFetch(
        `/v1/reviews/courses/${courseId}?page=${page}&size=${REVIEW_PAGE_SIZE}`
      );
      if (!res.ok) {
        setReviewsError('리뷰를 불러오지 못했어요.');
        return;
      }
      const data = await res.json();
      setReviews((prev) => (append ? [...prev, ...data.items] : data.items));
      setReviewsPage(data.page);
      setReviewsTotal(data.total);
    } catch {
      setReviewsError('서버에 연결할 수 없어요.');
    } finally {
      if (append) {
        setLoadingMoreReviews(false);
      } else {
        setReviewsLoading(false);
      }
    }
  };

  useEffect(() => {
    fetchReviews(1);
  }, [courseId]);

  const checkMyReview = async () => {
    if (!user) {
      setHasMyReview(false);
      return;
    }
    try {
      const res = await apiFetch('/v1/reviews/mine?page=1&size=100');
      if (!res.ok) return;
      const data = await res.json();
      setHasMyReview(data.items.some((review) => String(review.course_id) === String(courseId)));
    } catch {
      // 조용히 무시 - 확인 실패해도 작성 시도 자체는 가능하고, 이미 썼다면 백엔드가 최종 검증함
    }
  };

  useEffect(() => {
    checkMyReview();
  }, [user, courseId]);

  const handleLoadMoreReviews = () => {
    fetchReviews(reviewsPage + 1, { append: true });
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
    setReviewFormError('');
    setReviewSaving(true);
    try {
      const isEditing = editingReviewId != null;
      const url = isEditing ? `/v1/reviews/${editingReviewId}` : `/v1/reviews/courses/${courseId}`;
      const res = await apiFetch(url, {
        method: isEditing ? 'PATCH' : 'POST',
        body: JSON.stringify({ content: reviewContent, difficulty: reviewDifficulty }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewFormError(data?.detail ?? '리뷰 저장에 실패했어요.');
        return;
      }
      setReviewContent('');
      setReviewDifficulty('NORMAL');
      setEditingReviewId(null);
      await fetchReviews(1);
      await checkMyReview();
    } catch {
      setReviewFormError('서버에 연결할 수 없어요.');
    } finally {
      setReviewSaving(false);
    }
  };

  const handleDeleteReview = async (reviewId) => {
    setReviewActionError('');
    setDeletingReviewId(reviewId);
    try {
      const res = await apiFetch(`/v1/reviews/${reviewId}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '리뷰 삭제에 실패했어요.');
        return;
      }
      await fetchReviews(1);
      await checkMyReview();
    } catch {
      setReviewActionError('서버에 연결할 수 없어요.');
    } finally {
      setDeletingReviewId(null);
    }
  };

  const handleUploadImage = async (reviewId, event) => {
    const file = event.target.files[0];
    if (!file) return;
    setReviewActionError('');
    setUploadingImageReviewId(reviewId);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiFetch(`/v1/reviews/${reviewId}/images`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '이미지 업로드에 실패했어요.');
        return;
      }
      await fetchReviews(1);
    } catch {
      setReviewActionError('서버에 연결할 수 없어요.');
    } finally {
      event.target.value = '';
      setUploadingImageReviewId(null);
    }
  };

  const handleDeleteImage = async (reviewId, imageId) => {
    setReviewActionError('');
    try {
      const res = await apiFetch(`/v1/reviews/${reviewId}/images/${imageId}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setReviewActionError(data?.detail ?? '이미지 삭제에 실패했어요.');
        return;
      }
      await fetchReviews(1);
    } catch {
      setReviewActionError('서버에 연결할 수 없어요.');
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

          {user && !hasMyReview && (
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
                            <img src={image.image_url} alt="" />
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
