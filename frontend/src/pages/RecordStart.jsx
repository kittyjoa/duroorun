import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';

const DIFFICULTY_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };

const getPosition = () =>
  new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('geolocation-unsupported'));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 10000,
    });
  });

const formatElapsed = (totalSeconds) => {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

// pace: 초/km (백엔드가 duration_seconds / course.distance로 계산)
const formatPace = (paceSecondsPerKm) => {
  if (paceSecondsPerKm == null) return '정보 없음';
  const m = Math.floor(paceSecondsPerKm / 60);
  const s = Math.round(paceSecondsPerKm % 60);
  return `${m}'${String(s).padStart(2, '0')}" /km`;
};

const RecordStart = () => {
  const { courseType, courseId } = useParams();
  const navigate = useNavigate();
  const { user, isLoading: userLoading } = useUser();

  const [course, setCourse] = useState(null);
  const [courseError, setCourseError] = useState('');
  // idle | starting | running | paused | ending | finished
  const [phase, setPhase] = useState('idle');
  const [record, setRecord] = useState(null);
  const [result, setResult] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState('');
  const [blockedMessage, setBlockedMessage] = useState('');

  // 일시정지 누적 시간(ms)을 로컬에서 직접 추적한다 - RecordResponse엔
  // total_paused_seconds가 내려오지 않아서, pause/resume 시각을 기록해 계산한다.
  // (페이지를 새로고침하면 이 누적값은 초기화됨 - 진행 중 기록 복구 시 알려진 한계)
  const pausedAccumMsRef = useRef(0);
  const pausedAtRef = useRef(null);

  useEffect(() => {
    if (!userLoading && !user) {
      navigate('/login', { replace: true });
    }
  }, [userLoading, user, navigate]);

  useEffect(() => {
    let ignore = false;
    const fetchCourse = async () => {
      try {
        const res = await apiFetch(`/v1/courses/${courseType}/${courseId}`);
        if (ignore) return;
        if (!res.ok) {
          setCourseError('코스 정보를 불러오지 못했어요.');
          return;
        }
        setCourse(await res.json());
      } catch {
        if (!ignore) setCourseError('서버에 연결할 수 없어요.');
      }
    };
    fetchCourse();
    return () => {
      ignore = true;
    };
  }, [courseType, courseId]);

  // 새로고침 등으로 다시 들어왔을 때, 이미 진행 중인(종료 안 된) 기록이 있으면
  // 이어서 보여준다 (같은 유저는 진행 중 기록을 최대 1개만 가질 수 있음).
  useEffect(() => {
    let ignore = false;
    const checkActiveRecord = async () => {
      try {
        const res = await apiFetch('/v1/records/?page=1&size=1');
        if (ignore || !res.ok) return;
        const data = await res.json();
        const latest = data.items[0];
        if (!latest || latest.ended_at) return;

        if (String(latest.course_id) === String(courseId)) {
          setRecord(latest);
          if (latest.paused_at) {
            pausedAtRef.current = new Date(latest.paused_at).getTime();
            setPhase('paused');
          } else {
            setPhase('running');
          }
        } else {
          setBlockedMessage(
            '다른 코스에서 진행 중인 러닝 기록이 있어요. 먼저 그 기록을 종료해주세요.'
          );
        }
      } catch {
        // 조용히 무시 - 복구 실패해도 새로 시작하는 데는 지장 없음
      }
    };
    checkActiveRecord();
    return () => {
      ignore = true;
    };
  }, [courseId]);

  // 진행 중일 때만 1초마다 경과시간 갱신
  useEffect(() => {
    if (phase !== 'running' || !record) return undefined;
    const startedMs = new Date(record.started_at).getTime();
    const tick = () => {
      setElapsedSeconds(
        Math.max(0, Math.floor((Date.now() - startedMs - pausedAccumMsRef.current) / 1000))
      );
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [phase, record]);

  const handleStart = async () => {
    setError('');
    setPhase('starting');
    try {
      const position = await getPosition();
      const res = await apiFetch('/v1/records/start', {
        method: 'POST',
        body: JSON.stringify({
          course_id: Number(courseId),
          user_start_lat: position.coords.latitude,
          user_start_lng: position.coords.longitude,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '러닝을 시작하지 못했어요.');
        setPhase('idle');
        return;
      }
      const data = await res.json();
      pausedAccumMsRef.current = 0;
      pausedAtRef.current = null;
      setRecord(data);
      setElapsedSeconds(0);
      setPhase('running');
    } catch {
      setError('위치 정보를 가져올 수 없어요. 위치 권한을 확인해주세요.');
      setPhase('idle');
    }
  };

  const handlePause = async () => {
    setError('');
    try {
      const res = await apiFetch(`/v1/records/${record.record_id}/pause`, { method: 'PATCH' });
      if (!res.ok) {
        setError('일시정지에 실패했어요.');
        return;
      }
      pausedAtRef.current = Date.now();
      setPhase('paused');
    } catch {
      setError('서버에 연결할 수 없어요.');
    }
  };

  const handleResume = async () => {
    setError('');
    try {
      const res = await apiFetch(`/v1/records/${record.record_id}/resume`, { method: 'PATCH' });
      if (!res.ok) {
        setError('재시작에 실패했어요.');
        return;
      }
      if (pausedAtRef.current) {
        pausedAccumMsRef.current += Date.now() - pausedAtRef.current;
        pausedAtRef.current = null;
      }
      setPhase('running');
    } catch {
      setError('서버에 연결할 수 없어요.');
    }
  };

  const handleEnd = async () => {
    setError('');
    setPhase('ending');
    try {
      const position = await getPosition();
      const res = await apiFetch(`/v1/records/${record.record_id}/end`, {
        method: 'PATCH',
        body: JSON.stringify({
          user_end_lat: position.coords.latitude,
          user_end_lng: position.coords.longitude,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        // 종료 버튼을 누른 시점에 사용자 의도상 러닝은 끝난 것으로 본다 - 저장에
        // 실패해도(너무 짧음 등) 진행 중이던 화면(타이머)으로 되돌리지 않는다.
        setError(data?.detail ?? '러닝을 종료하지 못했어요.');
        setPhase('end_failed');
        return;
      }
      setResult(await res.json());
      setPhase('finished');
    } catch {
      setError('위치 정보를 가져올 수 없어요. 위치 권한을 확인해주세요.');
      setPhase('end_failed');
    }
  };

  if (userLoading || (!course && !courseError)) {
    return (
      <>
        <Header />
        <main className="record-page">
          <p className="course-list-status">불러오는 중...</p>
        </main>
      </>
    );
  }

  if (courseError) {
    return (
      <>
        <Header />
        <main className="record-page">
          <p className="course-list-status error">{courseError}</p>
        </main>
      </>
    );
  }

  return (
    <>
      <Header />
      <main className="record-page">
        <Link to={`/courses/${courseType}/${courseId}`} className="text-button">
          ← 코스로 돌아가기
        </Link>

        <div className="record-heading">
          <span className="section-kicker">러닝 기록</span>
          <h1>{course.course_name}</h1>
        </div>

        {error && <p className="course-list-status error">{error}</p>}

        {blockedMessage && phase === 'idle' && (
          <p className="course-list-status error">{blockedMessage}</p>
        )}

        {phase === 'idle' && !blockedMessage && (
          <div className="record-start-panel">
            <p className="record-hint">
              {course.difficulty &&
                `난이도: ${DIFFICULTY_LABEL[course.difficulty] ?? '정보 없음'} · `}
              {course.distance != null ? `${course.distance}km` : '거리 정보 없음'}
            </p>
            <button
              type="button"
              className="primary-button record-start-button"
              onClick={handleStart}
            >
              러닝 시작
            </button>
          </div>
        )}

        {phase === 'starting' && <p className="course-list-status">위치 확인 중...</p>}

        {(phase === 'running' || phase === 'paused' || phase === 'ending') && (
          <div className="record-start-panel">
            <div className="record-timer">{formatElapsed(elapsedSeconds)}</div>
            <p className={phase === 'running' ? 'record-hint record-live' : 'record-hint'}>
              {phase === 'paused' ? '일시정지됨' : '러닝 중'}
            </p>
            <div className="record-actions">
              {phase === 'running' && (
                <button
                  type="button"
                  className="primary-button record-end-button"
                  onClick={handlePause}
                >
                  일시정지
                </button>
              )}
              {phase === 'paused' && (
                <button
                  type="button"
                  className="primary-button record-end-button"
                  onClick={handleResume}
                >
                  재시작
                </button>
              )}
              <button
                type="button"
                className="primary-button record-end-button"
                onClick={handleEnd}
                disabled={phase === 'ending'}
              >
                {phase === 'ending' ? '종료 중...' : '러닝 종료'}
              </button>
            </div>
          </div>
        )}

        {phase === 'end_failed' && (
          <div className="record-start-panel record-result">
            <div className="record-timer">{formatElapsed(elapsedSeconds)}</div>
            <p className="record-hint">기록이 저장되지 않았어요</p>
            <Link
              to={`/courses/${courseType}/${courseId}`}
              className="primary-button record-end-button"
            >
              코스로 돌아가기
            </Link>
          </div>
        )}

        {phase === 'finished' && result && (
          <div className="record-start-panel record-result">
            <p className={`record-result-badge ${result.is_completed ? 'success' : ''}`}>
              {result.is_completed ? '완주 인증 완료' : '완주 인증 안 됨'}
            </p>
            <dl className="record-result-stats">
              <div>
                <dt>기록 시간</dt>
                <dd>{formatElapsed(result.duration_seconds ?? 0)}</dd>
              </div>
              <div>
                <dt>평균 페이스</dt>
                <dd>{formatPace(result.pace)}</dd>
              </div>
            </dl>
            {result.verification_message && (
              <p className="record-hint">{result.verification_message}</p>
            )}
            <Link
              to={`/courses/${courseType}/${courseId}`}
              className="primary-button record-end-button"
            >
              코스로 돌아가기
            </Link>
          </div>
        )}
      </main>
    </>
  );
};

export default RecordStart;
