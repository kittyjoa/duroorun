import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { refreshAccessToken } from '../api';
import { useUser } from '../contexts/UserContext';

const goToLoginWithError = (navigate, message) => {
  const params = new URLSearchParams({ error: message });
  navigate(`/login?${params}`, { replace: true });
};

const OAuthCallback = () => {
  const navigate = useNavigate();
  const { refreshUser } = useUser();
  // StrictMode가 개발 모드에서 effect를 두 번 실행하므로 재처리를 막아야 함
  const hasHandled = useRef(false);

  useEffect(() => {
    if (hasHandled.current) return;
    hasHandled.current = true;

    (async () => {
      try {
        // 이 경로는 이미 가입된(기존) 유저만 탄다 — 신규 유저는 계정이 아직 없어
        // 백엔드가 여기 대신 /onboarding?signup_token=...으로 바로 보낸다.
        // access_token은 URL에 노출하지 않고, 쿠키로 온 refresh_token으로 즉시 재발급받는다.
        const accessToken = await refreshAccessToken();
        if (!accessToken) {
          navigate('/login', { replace: true });
          return;
        }

        // refreshUser()가 전역 상태(Context)도 같이 채워서 헤더가 바로 반영된다.
        const { user, hasError } = await refreshUser();
        if (!user) {
          // 로그인 자체(access_token 발급)는 이미 성공했으므로, 일시적 서버 오류와
          // 진짜 인증 실패를 구분해 메시지를 다르게 보여준다.
          const message = hasError
            ? '일시적인 오류가 발생했어요. 잠시 후 다시 로그인해주세요.'
            : '로그인 처리 중 오류가 발생했어요. 다시 시도해주세요.';
          goToLoginWithError(navigate, message);
          return;
        }

        navigate('/', { replace: true });
      } catch {
        goToLoginWithError(navigate, '로그인 처리 중 오류가 발생했어요. 다시 시도해주세요.');
      }
    })();
  }, [navigate, refreshUser]);

  return <div className="oauth-callback">로그인 처리 중이에요...</div>;
};

export default OAuthCallback;
