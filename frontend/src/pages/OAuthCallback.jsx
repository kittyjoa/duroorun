import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { setAccessToken } from '../api';

const OAuthCallback = () => {
  const navigate = useNavigate();
  // StrictMode가 개발 모드에서 effect를 두 번 실행하는데, navigate() 이후 재실행되면
  // window.location.search에서 access_token이 이미 사라진 상태라 재처리를 막아야 함
  const hasHandled = useRef(false);

  useEffect(() => {
    if (hasHandled.current) return;
    hasHandled.current = true;

    const params = new URLSearchParams(window.location.search);
    const accessToken = params.get('access_token');
    const isNewUser = params.get('is_new_user') === 'true';

    if (!accessToken) {
      navigate('/login', { replace: true });
      return;
    }

    setAccessToken(accessToken);
    navigate(isNewUser ? '/onboarding' : '/', { replace: true });
  }, [navigate]);

  return <div className="oauth-callback">로그인 처리 중이에요...</div>;
};

export default OAuthCallback;
