import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import KakaoMap from '../components/map/KakaoMap';
import { useUser } from '../contexts/UserContext';

const DIFFICULTY_OPTIONS = [
  { value: 'EASY', label: '쉬움' },
  { value: 'NORMAL', label: '보통' },
  { value: 'HARD', label: '어려움' },
];

const COURSE_IMAGE_MAX_COUNT = 3;
const COURSE_IMAGE_MAX_SIZE_MB = 5;
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];

const EMPTY_FORM = {
  course_name: '',
  distance: '',
  difficulty: 'NORMAL',
  estimated_time: '',
  course_description: '',
};

// 강원도 대략적인 경계 박스
// - 사용자 GPS 위치가 강원도 일때 초기 화면으로 써도 되는지 가늠하는 용도
const _GANGWON_BOUNDS = { latMin: 37.0, latMax: 38.65, lngMin: 127.4, lngMax: 129.4 };
const _isNearGangwon = (point) =>
  point.lat >= _GANGWON_BOUNDS.latMin &&
  point.lat <= _GANGWON_BOUNDS.latMax &&
  point.lng >= _GANGWON_BOUNDS.lngMin &&
  point.lng <= _GANGWON_BOUNDS.lngMax;

const CustomCourseForm = () => {
  const { courseId } = useParams();
  const isEditMode = Boolean(courseId);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, isLoading: userLoading } = useUser();

  const [form, setForm] = useState(EMPTY_FORM);
  const [waypoints, setWaypoints] = useState([]); // [{lat, lng}] — 클릭한 순서가 곧 sequence
  const [images, setImages] = useState([]);
  const [ownerId, setOwnerId] = useState(null);
  const [loading, setLoading] = useState(isEditMode);
  const [saving, setSaving] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [error, setError] = useState('');
  // 코스 생성 직후 이 화면(수정)으로 넘어올 때 navigate state로 안내 문구를 실어 보냄
  const [notice, setNotice] = useState(location.state?.notice ?? '');
  // GPS: 지도 초기 위치를 잡아주는 편의 기능/ 경유지 좌표는 지도 클릭으로 가능
  // 강원도 밖 외지인들도 커스텀코스 생성하게 해야 지역관광의 의미가 있다고 판단.
  // GPS 위치가 강원 근처일 때만 그 좌표로 지도를 열고,
  // 그 외(강원 밖/GPS 거부/GPS 미지원)에는 항상 강원 기본 위치로 엶
  const [locationStatus, setLocationStatus] = useState('requesting'); // requesting|granted|denied|unsupported
  const [userLocation, setUserLocation] = useState(null);

  useEffect(() => {
    if (!navigator.geolocation) {
      setLocationStatus('unsupported');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocationStatus('granted');
      },
      () => setLocationStatus('denied'),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, []);

  useEffect(() => {
    if (!isEditMode) return undefined;
    let ignore = false;

    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await apiFetch(`/v1/courses/custom/${courseId}`);
        if (ignore) return;
        if (!res.ok) {
          setError(res.status === 404 ? '코스를 찾을 수 없어요.' : '코스 정보를 불러오지 못했어요.');
          return;
        }
        const data = await res.json();
        setForm({
          course_name: data.course_name ?? '',
          distance: data.distance ?? '',
          difficulty: data.difficulty ?? 'NORMAL',
          estimated_time: data.estimated_time ?? '',
          course_description: data.course_description ?? '',
        });
        setWaypoints((data.waypoints ?? []).map((w) => ({ lat: w.latitude, lng: w.longitude })));
        setImages(data.images ?? []);
        setOwnerId(data.created_by);
      } catch {
        if (!ignore) setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
      } finally {
        if (!ignore) setLoading(false);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [isEditMode, courseId]);

  const handleFieldChange = (field) => (event) => {
    setForm({ ...form, [field]: event.target.value });
  };

  const handleMapClick = useCallback((point) => {
    setWaypoints((prev) => [...prev, point]);
  }, []);

  const handleRemoveWaypoint = (index) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');

    if (waypoints.length < 2) {
      setError('경유지를 지도에서 2개 이상 클릭해주세요.');
      return;
    }

    const body = {
      course_name: form.course_name,
      distance: Number(form.distance),
      difficulty: form.difficulty,
      estimated_time: Number(form.estimated_time),
      course_description: form.course_description || null,
      waypoints: waypoints.map((p) => ({ latitude: p.lat, longitude: p.lng })),
    };

    setSaving(true);
    try {
      const res = await apiFetch(
        isEditMode ? `/v1/courses/custom/${courseId}` : '/v1/courses/custom',
        { method: isEditMode ? 'PATCH' : 'POST', body: JSON.stringify(body) },
      );

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '저장에 실패했어요.');
        return;
      }

      const data = await res.json();
      if (isEditMode) {
        setNotice('저장됐어요');
      } else {
        // 이미지는 코스가 생성된 뒤에만 업로드 가능(courseId 필요) — 생성 직후 수정 화면으로 이동
        navigate(`/courses/custom/${data.course_id}/edit`, {
          replace: true,
          state: { notice: '코스가 생성됐어요! 사진도 추가해보세요.' },
        });
      }
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setSaving(false);
    }
  };

  const handleImageUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    setError('');

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setError('지원하지 않는 이미지 형식입니다 (jpg, png, webp, gif만 가능)');
      event.target.value = '';
      return;
    }
    if (file.size > COURSE_IMAGE_MAX_SIZE_MB * 1024 * 1024) {
      setError(`이미지 크기는 최대 ${COURSE_IMAGE_MAX_SIZE_MB}MB까지 업로드 가능합니다`);
      event.target.value = '';
      return;
    }

    setUploadingImage(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiFetch(`/v1/courses/custom/${courseId}/images`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '이미지 업로드에 실패했어요');
        return;
      }
      const data = await res.json();
      setImages(data.images ?? []);
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      event.target.value = '';
      setUploadingImage(false);
    }
  };

  const handleImageDelete = async (imageId) => {
    setError('');
    try {
      const res = await apiFetch(`/v1/courses/custom/${courseId}/images/${imageId}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        setError('이미지 삭제에 실패했어요');
        return;
      }
      setImages((prev) => prev.filter((img) => img.image_id !== imageId));
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('정말 이 코스를 삭제하시겠어요?')) return;
    setError('');
    try {
      const res = await apiFetch(`/v1/courses/custom/${courseId}`, { method: 'DELETE' });
      if (!res.ok) {
        setError('삭제에 실패했어요');
        return;
      }
      navigate('/courses');
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    }
  };

  if (!userLoading && !user) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status error">로그인 후 이용할 수 있어요.</p>
        </main>
      </>
    );
  }

  if (isEditMode && !loading && user && ownerId !== user.user_id) {
    return (
      <>
        <Header />
        <main className="course-detail-page">
          <p className="course-list-status error">본인의 코스만 수정할 수 있어요.</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="course-detail-page">
        <h1>{isEditMode ? '커스텀 코스 수정' : '커스텀 코스 만들기'}</h1>
        <p className="course-detail-desc">커스텀 코스는 현재 강원도 지역에서만 만들 수 있어요.</p>

        {loading && <p className="course-list-status">불러오는 중...</p>}

        {!loading && (
          <form className="course-form" onSubmit={handleSubmit}>
            <label htmlFor="course_name">코스명</label>
            <input
              id="course_name"
              value={form.course_name}
              onChange={handleFieldChange('course_name')}
              required
            />

            <label htmlFor="distance">거리 (km)</label>
            <input
              id="distance"
              type="number"
              min="0.1"
              step="0.1"
              value={form.distance}
              onChange={handleFieldChange('distance')}
              required
            />

            <label htmlFor="difficulty">난이도</label>
            <select id="difficulty" value={form.difficulty} onChange={handleFieldChange('difficulty')}>
              {DIFFICULTY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <label htmlFor="estimated_time">예상 소요시간 (분)</label>
            <input
              id="estimated_time"
              type="number"
              min="1"
              value={form.estimated_time}
              onChange={handleFieldChange('estimated_time')}
              required
            />

            <label htmlFor="course_description">코스 설명</label>
            <textarea
              id="course_description"
              rows={4}
              value={form.course_description}
              onChange={handleFieldChange('course_description')}
            />

            <label>경유지 (지도를 클릭해서 순서대로 추가)</label>
            {!isEditMode && locationStatus === 'requesting' ? (
              // GPS 응답이 지도 SDK 로드보다 느린 경우가 많아, 위치가 잡히기 전에 지도부터
              // 띄우면 아래 initialCenter 판단(강원 근처인지)이 반영 안 된 채로 초기화돼버림
              // — 다만 GPS는 이제 필수가 아니라서(거부/미지원이어도 폼은 그대로 진행)
              // 결과를 기다리는 잠깐의 대기일 뿐, 막는 게 아님
              <p className="course-list-status">위치 정보를 가져오는 중...</p>
            ) : (
              <KakaoMap
                path={waypoints}
                editable
                onMapClick={handleMapClick}
                // GPS 위치가 강원 근처일 때만 그 좌표로 열고, 아니면(강원 밖/거부/미지원)
                // KakaoMap 자체의 강원 기본 좌표(_FALLBACK_CENTER)로 열리게 둠
                initialCenter={
                  locationStatus === 'granted' && userLocation && _isNearGangwon(userLocation)
                    ? userLocation
                    : undefined
                }
                emptyHint="지도를 클릭해서 경유지를 추가하세요"
              />
            )}
            {waypoints.length > 0 && (
              <ul className="waypoint-list">
                {waypoints.map((p, index) => (
                  // eslint-disable-next-line react/no-array-index-key -- 좌표만으로는 중복 클릭 시 key 충돌 가능, 순서 자체가 의미있는 값이라 index가 자연스러움
                  <li key={index}>
                    <span>
                      {index + 1}. {p.lat.toFixed(5)}, {p.lng.toFixed(5)}
                    </span>
                    <button type="button" onClick={() => handleRemoveWaypoint(index)}>
                      삭제
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {isEditMode && (
              <>
                <label>사진 (최대 {COURSE_IMAGE_MAX_COUNT}장)</label>
                <div className="course-detail-images">
                  {images.map((image) => (
                    <div key={image.image_id} className="course-form-image">
                      <img src={image.image_url} alt="" />
                      <button type="button" onClick={() => handleImageDelete(image.image_id)}>
                        삭제
                      </button>
                    </div>
                  ))}
                </div>
                {images.length < COURSE_IMAGE_MAX_COUNT && (
                  <label className="mypage-image-upload">
                    {uploadingImage ? '업로드 중...' : '사진 추가'}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/gif"
                      onChange={handleImageUpload}
                      disabled={uploadingImage}
                      hidden
                    />
                  </label>
                )}
              </>
            )}

            {error && <p className="onboarding-error">{error}</p>}
            {notice && <p className="mypage-success">{notice}</p>}

            <div className="course-form-actions">
              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? '저장 중...' : '저장하기'}
              </button>
              {isEditMode && (
                <button type="button" className="text-button" onClick={handleDelete}>
                  코스 삭제
                </button>
              )}
            </div>
          </form>
        )}
      </main>
    </>
  );
};

export default CustomCourseForm;
