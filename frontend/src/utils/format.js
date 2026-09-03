// 러닝 기록 화면(RecordStart, RecordHistory)에서 공통으로 쓰는 시간/페이스 표시 포맷터

export const formatElapsed = (totalSeconds) => {
  if (totalSeconds == null) return '정보 없음';
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

// pace: 초/km (백엔드가 duration_seconds / course.distance로 계산)
export const formatPace = (paceSecondsPerKm) => {
  if (paceSecondsPerKm == null) return '정보 없음';
  // 분/초를 각각 반올림하면 초가 59.5 이상일 때 "5'60""처럼 나올 수 있어서,
  // 전체 초를 먼저 반올림한 뒤 분/초로 나눈다
  const totalSeconds = Math.round(paceSecondsPerKm);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}'${String(s).padStart(2, '0')}" /km`;
};
