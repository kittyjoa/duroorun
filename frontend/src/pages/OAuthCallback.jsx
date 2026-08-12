import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiFetch, refreshAccessToken } from '../api';

const goToLoginWithError = (navigate, message) => {
  const params = new URLSearchParams({ error: message });
  navigate(`/login?${params}`, { replace: true });
};

const OAuthCallback = () => {
  const navigate = useNavigate();
  // StrictMode가 개발 모드에서 effect를 두 번 실행하므로 재처리를 막아야 함
  const hasHandled = useRef(false);

  useEffect(() => {
    if (hasHandled.current) return;
    hasHandled.current = true;

    (async () => {
      try {
        // access_token은 URL에 노출하지 않고, 쿠키로 온 refresh_token으로 즉시 재발급받는다.
        const accessToken = await refreshAccessToken();
        if (!accessToken) {
          navigate('/login', { replace: true });
          return;
        }

        // is_new_user 대신 실제 프로필(닉네임/거주지) 값 기준으로 온보딩 필요 여부를 판단한다.
        // 온보딩을 중간에 그만둔 유저도 다음 로그인 때 다시 온보딩으로 보내기 위함.
        const res = await apiFetch('/v1/users/me');
        const user = res.ok ? await res.json() : null;
        const needsOnboarding = !user || !user.nickname || !user.location;

        navigate(needsOnboarding ? '/onboarding' : '/', { replace: true });
      } catch {
        goToLoginWithError(navigate, '로그인 처리 중 오류가 발생했어요. 다시 시도해주세요.');
      }
    })();
  }, [navigate]);

  return <div className="oauth-callback">로그인 처리 중이에요...</div>;
};

export default OAuthCallback;
