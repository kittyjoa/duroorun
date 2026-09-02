import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

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

// 강원도 대략적인 경계 박스 (app/domain/course/schemas.py의 _GANGWON_MAIN_BOX/_CHEORWON_BOX와 동일)
// - 사용자 GPS 위치가 강원도 일때 초기 화면으로 써도 되는지 가늠하는 용도 + 경유지 클릭 시 지역 검증
// - 사각형 1개로 구현하면 서울도 포함돼서 강원 본토 박스 + 철원군 전용 박스 2개
const _GANGWON_BOXES = [
  { latMin: 36.9, latMax: 38.7, lngMin: 127.4, lngMax: 129.5 }, // 강원 본토
  { latMin: 37.95, latMax: 38.45, lngMin: 127.0, lngMax: 127.45 }, // 철원군 (38선 이북이라 서울과 안 겹침)
];
const _isNearGangwon = (point) =>
  _GANGWON_BOXES.some(
    (box) =>
      point.lat >= box.latMin &&
      point.lat <= box.latMax &&
      point.lng >= box.lngMin &&
      point.lng <= box.lngMax,
  );

// Haversine 방식으로 두 좌표 간 직선거리 측정
const _haversineDistanceKm = (a, b) => {
  const R = 6371;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
};

// 경유지를 순서대로 이은 직선 구간 거리의 합 (실제 도로 굴곡은 반영 안 됨 — 근사치)
const _totalDistanceKm = (points) => {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += _haversineDistanceKm(points[i - 1], points[i]);
  }
  return total;
};

const CustomCourseForm = () => {
  const { courseId } = useParams();
  const isEditMode = Boolean(courseId);
  const navigate = useNavigate();
  const { user, isLoading: userLoading } = useUser();

  const [form, setForm] = useState(EMPTY_FORM);
  const [waypoints, setWaypoints] = useState([]); // [{lat, lng}] — 클릭한 순서가 곧 sequence
  const [images, setImages] = useState([]);
  const [ownerId, setOwnerId] = useState(null);
  const [loading, setLoading] = useState(isEditMode);
  const [saving, setSaving] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // 신규 생성 저장 직후에만 씀: 완료 모달에서 "사진 추가"/"나만의 코스로 이동" 선택
  const [createdCourseId, setCreatedCourseId] = useState(null);
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

  // '사진 추가하기'로 넘어온 경우(#course-photos-section) 사진 영역까지 자동 스크롤.
  // 사진 섹션은 isEditMode && !loading일 때만 DOM에 존재하므로 그 시점에 실행.
  useEffect(() => {
    if (!isEditMode || loading) return;
    if (window.location.hash !== '#course-photos-section') return;
    document.getElementById('course-photos-section')?.scrollIntoView({ behavior: 'smooth' });
  }, [isEditMode, loading]);

  const handleFieldChange = (field) => (event) => {
    setForm({ ...form, [field]: event.target.value });
  };

  // 지도 클릭/삭제로 경유지가 바뀔 때만 거리 자동계산(재기입) — 수정 모드 진입 시
  // 서버에서 불러온 기존 waypoints/distance는 이 핸들러를 거치지 않으므로 덮어쓰지 않음
  const handleMapClick = useCallback((point) => {
    // 강원도 밖 클릭은 아예 경유지로 추가하지 않음
    // ㅡ 지도 클릭 시점에 바로 알려줌
    if (!_isNearGangwon(point)) {
      setError('강원도 지역 내 좌표만 경유지로 추가할 수 있어요.');
      return;
    }
    setError('');
    setWaypoints((prev) => {
      const next = [...prev, point];
      setForm((f) => ({
        ...f,
        distance: next.length >= 2 ? _totalDistanceKm(next).toFixed(1) : '',
      }));
      return next;
    });
  }, []);

  const handleRemoveWaypoint = (index) => {
    setWaypoints((prev) => {
      const next = prev.filter((_, i) => i !== index);
      setForm((f) => ({
        ...f,
        distance: next.length >= 2 ? _totalDistanceKm(next).toFixed(1) : '',
      }));
      return next;
    });
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
        // 완료 모달에서 사용자가 사진 추가/목록 이동을 직접 고르게 함
        setCreatedCourseId(data.course_id);
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
        <p className="course-detail-desc">🏃 커스텀 코스는 현재 강원도 지역에서만 만들 수 있어요.</p>

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

            <label htmlFor="difficulty">난이도</label>
            <select id="difficulty" value={form.difficulty} onChange={handleFieldChange('difficulty')}>
              {DIFFICULTY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <label htmlFor="course_description">코스 설명</label>
            <textarea
              id="course_description"
              rows={4}
              value={form.course_description}
              onChange={handleFieldChange('course_description')}
            />

            <label>경유지 (지도를 클릭해서 순서대로 추가)</label>
            <p className="kakao-map-hint-static">⚠️ 지도가 제대로 표시되지 않으면 새로고침을 한번 해주세요</p>
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
            <p className="kakao-map-hint-static">
              지도에 찍는 좌표를 바탕으로 거리를 자동 계산합니다. 직접 수정도 가능합니다.
            </p>

            <label htmlFor="estimated_time">예상 소요시간 (분)</label>
            <input
              id="estimated_time"
              type="number"
              min="1"
              value={form.estimated_time}
              onChange={handleFieldChange('estimated_time')}
              required
            />

            {isEditMode && (
              <div id="course-photos-section">
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
              </div>
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

      {createdCourseId != null && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="코스 저장 완료">
          <div className="review-modal-card">
            <h2>저장이 완료되었습니다</h2>
            <p>사진을 추가해서 코스를 더 알아보기 쉽게 꾸며보세요.</p>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, marginTop: 20 }}>
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  // /new와 /:courseId/edit이 같은 컴포넌트라 navigate만으로는 리마운트되지 않음
                  // ㅡ createdCourseId를 직접 비워야 모달이 edit 화면 위에 안 남음
                  setCreatedCourseId(null);
                  navigate(`/courses/custom/${createdCourseId}/edit#course-photos-section`, {
                    replace: true,
                  });
                }}
              >
                사진 추가하기
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setCreatedCourseId(null);
                  navigate('/courses/custom/mine');
                }}
              >
                나만의 코스로 이동
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default CustomCourseForm;
