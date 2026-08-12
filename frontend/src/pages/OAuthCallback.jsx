import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { refreshAccessToken } from '../api';

const OAuthCallback = () => {
  const navigate = useNavigate();
  // StrictMode가 개발 모드에서 effect를 두 번 실행하므로 재처리를 막아야 함
  const hasHandled = useRef(false);

  useEffect(() => {
    if (hasHandled.current) return;
    hasHandled.current = true;

    const isNewUser = new URLSearchParams(window.location.search).get('is_new_user') === 'true';

    // access_token은 URL에 노출하지 않고, 쿠키로 온 refresh_token으로 즉시 재발급받는다.
    refreshAccessToken().then((accessToken) => {
      if (!accessToken) {
        navigate('/login', { replace: true });
        return;
      }
      navigate(isNewUser ? '/onboarding' : '/', { replace: true });
    });
  }, [navigate]);

  return <div className="oauth-callback">로그인 처리 중이에요...</div>;
};

export default OAuthCallback;
