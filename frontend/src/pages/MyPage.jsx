import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import useFocusTrap from '../hooks/useFocusTrap';

// 백엔드 검증 규칙과 동일 (app/config.py) — 서버가 최종 검증하고, 여긴 UX용 사전 안내
const NICKNAME_PATTERN = '[가-힣a-zA-Z0-9]{2,10}';
const LOCATION_PATTERN = '[가-힣a-zA-Z0-9\\s]{1,50}';
const PROFILE_IMAGE_MAX_SIZE_MB = 2;

const MyPage = () => {
  const navigate = useNavigate();
  const imageModalRef = useRef(null);
  const reviewModalRef = useRef(null);
  const { user, setUser, isLoading } = useUser();

  const [nickname, setNickname] = useState('');
  const [location, setLocation] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [isImageOpen, setIsImageOpen] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);

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
    if (!isLoading && !user) {
      navigate('/login', { replace: true });
    }
  }, [isLoading, user, navigate]);

  useEffect(() => {
    if (user) {
      setNickname(user.nickname || '');
      setLocation(user.location || '');
    }
  }, [user]);

  useFocusTrap(imageModalRef, isImageOpen);
  useFocusTrap(reviewModalRef, isReviewOpen);

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

  return (
    <>
      <Header />
      <main className="mypage-page">
        <h1>마이페이지</h1>

        {isLoading && <p>불러오는 중...</p>}
        {!isLoading && !user && <p>정보를 불러오지 못했어요.</p>}

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
                  <span>{(user.nickname || '두').charAt(0)}</span>
                </div>
              )}
              <label className="mypage-image-upload">
                {uploading ? '업로드 중...' : '프로필 사진 변경'}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleImageChange}
                  disabled={uploading}
                  hidden
                />
              </label>
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
            <p>준비 중이에요. 조금만 기다려주세요!</p>
          </div>
        </div>
      )}
    </>
  );
};

export default MyPage;
