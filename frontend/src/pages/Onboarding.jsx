import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiFetch, setAccessToken } from '../api';
import { useUser } from '../contexts/UserContext';

// TODO: 실제 이용약관/개인정보처리방침 문구로 교체
const TERMS_PLACEHOLDER = `[이용약관 및 개인정보처리방침 - 준비 중]

두루런 서비스 이용을 위해 아래 약관에 동의해주세요.
(실제 약관 문구는 추후 반영 예정입니다)`;

const Onboarding = () => {
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [nickname, setNickname] = useState('');
  const [location, setLocation] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const { refreshUser } = useUser();

  // 신규 유저만 이 페이지에 signup_token을 들고 도착한다 (백엔드가 콜백에서 그렇게 리다이렉트함).
  // 이 값 없이는 계정을 만들 수 없으므로, 직접 URL로 들어온 경우 로그인부터 다시 시키기 위해 막는다.
  // 최초 렌더 시점에 한 번만 읽어 state로 옮겨 담는다 - 아래 effect가 URL에서 바로 지우므로,
  // 이후 다시 읽으면 못 찾는다.
  const [signupToken] = useState(
    () => new URLSearchParams(window.location.search).get('signup_token')
  );

  useEffect(() => {
    if (!signupToken) {
      navigate('/login', { replace: true });
      return;
    }
    // signup_token이 URL에 남아있으면 브라우저 히스토리/화면 공유/access log 등으로 새어나갈
    // 수 있으니, state로 옮겨 담은 직후 바로 지운다 (2026-09-11 리뷰 지적 - 계정 생성 권한을
    // 가진 1회용 토큰이 access_token/refresh_token과 달리 URL에 그대로 실려 있었음)
    window.history.replaceState(null, '', '/onboarding');
  }, [signupToken, navigate]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');

    if (!agreeTerms) {
      setError('이용약관 및 개인정보처리방침에 동의해야 가입할 수 있어요');
      return;
    }

    setSubmitting(true);
    try {
      const res = await apiFetch('/v1/auth/complete-signup', {
        method: 'POST',
        body: JSON.stringify({
          signup_token: signupToken,
          agree_terms: agreeTerms,
          nickname,
          location,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail ?? '가입 완료 중 오류가 발생했어요');
        return;
      }

      const data = await res.json();
      // 이 응답이 로그인의 시작점 — 여기서 처음으로 토큰이 생기고 계정도 이때 만들어진다.
      setAccessToken(data.access_token);
      await refreshUser();
      navigate('/', { replace: true });
    } catch {
      setError('서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
    } finally {
      setSubmitting(false);
    }
  };

  if (!signupToken) return null;

  return (
    <div className="onboarding-page">
      <form className="onboarding-card" onSubmit={handleSubmit}>
        <h1>거의 다 왔어요!</h1>
        <p className="onboarding-desc">약관에 동의하고, 두루런에서 쓸 닉네임과 거주지를 알려주세요</p>

        <div className="onboarding-terms-box">{TERMS_PLACEHOLDER}</div>
        <label className="onboarding-checkbox">
          <input
            type="checkbox"
            checked={agreeTerms}
            onChange={(event) => setAgreeTerms(event.target.checked)}
          />
          이용약관 및 개인정보처리방침에 동의합니다 (필수)
        </label>

        <label htmlFor="nickname">닉네임</label>
        <input
          id="nickname"
          value={nickname}
          onChange={(event) => setNickname(event.target.value)}
          placeholder="한글/영문/숫자 2~10자"
          required
        />

        <label htmlFor="location">거주지</label>
        <input
          id="location"
          value={location}
          onChange={(event) => setLocation(event.target.value)}
          placeholder="예: 강원 속초시"
          required
        />

        {error && <p className="onboarding-error">{error}</p>}

        <button type="submit" className="primary-button" disabled={submitting || !agreeTerms}>
          {submitting ? '처리 중...' : '가입 완료'}
        </button>
      </form>
    </div>
  );
};

export default Onboarding;
