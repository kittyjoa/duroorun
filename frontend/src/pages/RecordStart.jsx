import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { apiFetch } from '../api';
import Header from '../components/layout/Header';
import { useUser } from '../contexts/UserContext';
import { DIFFICULTY_LABEL } from '../utils/difficulty';
import { formatElapsed, formatPace } from '../utils/format';

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
  // end_failed 화면에서 "기록이 저장되지 않았어요"를 보여줄지 판단하는 데 쓴다. GPS
  // 실패는 서버에 종료 요청 자체가 안 나간 것이라 기록이 여전히 멀쩡히 진행 중이므로,
  // 저장 실패와 다른 안내를 보여준다.
  const [endFailedIsGps, setEndFailedIsGps] = useState(false);
  // 다른 코스에서 진행 중인 기록이 있을 때, 그 기록 화면으로 바로 이동할 수 있게 위치를 기억해둔다
  const [blockedRecordTarget, setBlockedRecordTarget] = useState(null);

  // 일시정지 누적 시간(ms)을 로컬에서 직접 추적한다 - 진행 중(pause/resume 시각)엔
  // 여기서 직접 계산하고, 새로고침 등으로 진행 중인 기록을 복구할 때는 checkActiveRecord가
  // 서버가 내려주는 total_paused_seconds로 이 값을 다시 채워넣는다.
  const pausedAccumMsRef = useRef(0);
  const pausedAtRef = useRef(null);
  // 이 라우트는 courseId만 바뀌며 같은 컴포넌트가 재사용된다(SPA 내비게이션, 브라우저
  // 뒤로가기 등) - GPS 응답을 기다리는 동안 다른 코스 화면으로 넘어갔는지 대조하기 위해
  // 매 렌더마다 최신 courseId로 갱신해둔다.
  const activeCourseIdRef = useRef(courseId);
  activeCourseIdRef.current = courseId;

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
    // 인증 정보가 아직 로딩 중이면 accessToken 없이 요청이 나가 401을 받고 조용히
    // 무시되어(catch에서 잡히지 않고 !res.ok로 return), 실제로 진행 중인 기록이 있어도
    // 잠깐 "idle" 화면으로 보일 수 있다 - user가 확정된 뒤에 실행한다
    if (userLoading || !user) return undefined;
    let ignore = false;
    const checkActiveRecord = async () => {
      // courseId가 바뀌어 effect가 재실행될 때(SPA 내비게이션, 브라우저 뒤로가기 등) 이전
      // courseId에서 떴던 차단 메시지/진행 화면이 상황이 해소된 뒤에도 남아있지 않도록
      // 초기화한다 - phase/record를 안 지우면, "B에서 진행 중인 A로 이동 → 뒤로가기로
      // B로 복귀"처럼 두 코스를 오갈 때 B 화면인데 A의 타이머가 계속 보이는 문제가 있었다
      setBlockedMessage('');
      setBlockedRecordTarget(null);
      setError('');
      setPhase('idle');
      setRecord(null);
      try {
        const res = await apiFetch('/v1/records/?page=1&size=1');
        if (ignore || !res.ok) return;
        const data = await res.json();
        const latest = data.items[0];
        if (!latest || latest.ended_at) return;

        if (String(latest.course_id) === String(courseId)) {
          setRecord(latest);
          const startedMs = new Date(latest.started_at).getTime();
          const pausedAccumMs = (latest.total_paused_seconds ?? 0) * 1000;
          pausedAccumMsRef.current = pausedAccumMs;

          if (latest.paused_at) {
            const pausedAtMs = new Date(latest.paused_at).getTime();
            pausedAtRef.current = pausedAtMs;
            setElapsedSeconds(Math.max(0, Math.floor((pausedAtMs - startedMs - pausedAccumMs) / 1000)));
            setPhase('paused');
          } else {
            setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedMs - pausedAccumMs) / 1000)));
            setPhase('running');
          }
        } else {
          setBlockedMessage(
            '다른 코스에서 진행 중인 러닝 기록이 있어요. 먼저 그 기록을 종료해주세요.'
          );
          setBlockedRecordTarget({
            courseType: latest.course_type.toLowerCase(),
            courseId: latest.course_id,
          });
        }
      } catch {
        // 조용히 무시 - 복구 실패해도 새로 시작하는 데는 지장 없음
      }
    };
    checkActiveRecord();
    return () => {
      ignore = true;
    };
  }, [courseId, courseType, userLoading, user]);

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
    // GPS 응답을 기다리는 동안(최대 10초) 다른 코스 화면으로 이동했을 수 있다 - 같은
    // 컴포넌트가 재사용되므로, 그 사이 이동했다면 지금 보고 있는 화면을 이 요청의
    // 결과로 건드리지 않는다 (요청 자체도 더 이상 보낼 필요가 없어 취소한다)
    const requestedCourseId = courseId;
    const isStale = () => activeCourseIdRef.current !== requestedCourseId;
    setError('');
    setPhase('starting');

    let position;
    try {
      position = await getPosition();
    } catch {
      if (!isStale()) {
        setError('위치 정보를 가져올 수 없어요. 위치 권한을 확인해주세요.');
        setPhase('idle');
      }
      return;
    }
    if (isStale()) return;

    try {
      const res = await apiFetch('/v1/records/start', {
        method: 'POST',
        body: JSON.stringify({
          course_id: Number(courseId),
          user_start_lat: position.coords.latitude,
          user_start_lng: position.coords.longitude,
        }),
      });
      if (isStale()) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '러닝을 시작하지 못했어요.');
        setPhase('idle');
        return;
      }
      const data = await res.json();
      if (isStale()) return;
      pausedAccumMsRef.current = 0;
      pausedAtRef.current = null;
      setRecord(data);
      setElapsedSeconds(0);
      setPhase('running');
    } catch {
      if (!isStale()) {
        setError('서버에 연결할 수 없어요.');
        setPhase('idle');
      }
    }
  };

  const handlePause = async () => {
    // 응답을 기다리는 사이 다른 코스 화면으로 이동했을 수 있다(같은 컴포넌트가 재사용되므로) -
    // 그러면 지금 보고 있는 화면을 이 응답으로 건드리지 않는다
    const requestedCourseId = courseId;
    const isStale = () => activeCourseIdRef.current !== requestedCourseId;
    setError('');
    try {
      const res = await apiFetch(`/v1/records/${record.record_id}/pause`, { method: 'PATCH' });
      if (isStale()) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '일시정지에 실패했어요.');
        return;
      }
      pausedAtRef.current = Date.now();
      setPhase('paused');
    } catch {
      if (!isStale()) setError('서버에 연결할 수 없어요.');
    }
  };

  const handleResume = async () => {
    const requestedCourseId = courseId;
    const isStale = () => activeCourseIdRef.current !== requestedCourseId;
    setError('');
    try {
      const res = await apiFetch(`/v1/records/${record.record_id}/resume`, { method: 'PATCH' });
      if (isStale()) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '재시작에 실패했어요.');
        return;
      }
      if (pausedAtRef.current) {
        pausedAccumMsRef.current += Date.now() - pausedAtRef.current;
        pausedAtRef.current = null;
      }
      setPhase('running');
    } catch {
      if (!isStale()) setError('서버에 연결할 수 없어요.');
    }
  };

  // "이미 종료된 기록입니다" 실패는 이 record_id에 대해 종료 요청이 이전에 이미 서버에
  // 성공적으로 처리됐다는 뜻이다(네트워크 에러로 그 응답을 못 받고 "저장 안 됨"으로 표시된 뒤
  // "다시 시도"를 눌렀을 때 등). 실제 저장된 결과를 조회해서 보여준다. 성공하면 true.
  // isStale은 호출한 쪽(handleEnd)의 코스 staleness 체크를 그대로 넘겨받아, 조회하는
  // 사이 다른 코스 화면으로 이동했으면 그 결과로 지금 화면을 건드리지 않는다.
  const tryShowActualResult = async (recordId, isStale) => {
    try {
      const checkRes = await apiFetch(`/v1/records/${recordId}`);
      if (isStale()) return true;
      if (checkRes.ok) {
        const checkData = await checkRes.json();
        if (isStale()) return true;
        if (checkData.ended_at) {
          setResult(checkData);
          setPhase('finished');
          return true;
        }
      }
    } catch {
      // 재확인도 실패하면 호출한 쪽에서 그냥 에러로 처리한다
    }
    return false;
  };

  const handleEnd = async () => {
    // handlePause/handleResume와 동일하게, 응답을 기다리는 사이 다른 코스로 이동했을 수
    // 있다(같은 컴포넌트가 재사용되므로) - 그러면 지금 보고 있는 화면을 이 요청의 결과로
    // 건드리지 않는다. record는 비동기 처리 중 바뀔 수 있으니 시작 시점 값을 캡처해둔다.
    const requestedCourseId = courseId;
    const requestedRecordId = record.record_id;
    const isStale = () => activeCourseIdRef.current !== requestedCourseId;

    setError('');
    setPhase('ending');

    let position;
    try {
      position = await getPosition();
    } catch {
      if (isStale()) return;
      // GPS 실패 자체는 이번 시도가 서버에 안 나간 것이지만, "다시 시도" 흐름에서는
      // 이전 시도가 이미 서버에 성공했을 수 있다(응답만 유실됐던 경우) - 그 경우까지
      // "기록은 계속 진행 중"이라고 잘못 안내하지 않도록 먼저 실제 결과를 확인한다
      if (await tryShowActualResult(requestedRecordId, isStale)) return;
      setError('위치 정보를 가져올 수 없어요. 위치 권한을 확인해주세요.');
      setEndFailedIsGps(true);
      setPhase('end_failed');
      return;
    }
    if (isStale()) return;
    setEndFailedIsGps(false);

    try {
      const res = await apiFetch(`/v1/records/${requestedRecordId}/end`, {
        method: 'PATCH',
        body: JSON.stringify({
          user_end_lat: position.coords.latitude,
          user_end_lng: position.coords.longitude,
        }),
      });
      if (isStale()) return;
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        // "이미 종료된 기록"은 실패가 아니라, 이전 시도가 실제로는 성공했다는 뜻이다 -
        // (예: 네트워크 에러로 "저장 안 됨"이 떴던 걸 "다시 시도"로 재요청한 경우) 그
        // 이전 결과를 그대로 보여준다.
        if (
          data?.detail === '이미 종료된 기록입니다.' &&
          (await tryShowActualResult(requestedRecordId, isStale))
        ) {
          return;
        }
        if (isStale()) return;
        // 종료 버튼을 누른 시점에 사용자 의도상 러닝은 끝난 것으로 본다 - 저장에
        // 실패해도(너무 짧음 등) 진행 중이던 화면(타이머)으로 되돌리지 않는다.
        setError(data?.detail ?? '러닝을 종료하지 못했어요.');
        setPhase('end_failed');
        return;
      }
      const finished = await res.json();
      if (isStale()) return;
      setResult(finished);
      setPhase('finished');
    } catch {
      if (isStale()) return;
      // 네트워크 에러(응답 자체를 못 받음)일 수 있어, 실제로 서버에 저장됐는지 다시
      // 확인한다 - 요청은 서버에 도달해 처리됐는데 응답만 유실된 경우 "저장 안 됨"으로
      // 잘못 안내하는 걸 방지하기 위함
      if (await tryShowActualResult(requestedRecordId, isStale)) return;
      if (isStale()) return;
      setError('서버에 연결할 수 없어요.');
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
          <div className="record-start-panel">
            <p className="course-list-status error">{blockedMessage}</p>
            {blockedRecordTarget && (
              <Link
                to={`/records/start/${blockedRecordTarget.courseType}/${blockedRecordTarget.courseId}`}
                className="primary-button record-end-button"
              >
                진행 중인 기록으로 이동
              </Link>
            )}
          </div>
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
            <p className="record-hint">
              {endFailedIsGps ? '위치 확인에 실패했어요. 기록은 계속 진행 중이에요.' : '기록이 저장되지 않았어요'}
            </p>
            <div className="review-item-actions">
              <button type="button" className="primary-button record-end-button" onClick={handleEnd}>
                다시 시도
              </button>
              <Link to={`/courses/${courseType}/${courseId}`} className="text-button">
                코스로 돌아가기
              </Link>
            </div>
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
