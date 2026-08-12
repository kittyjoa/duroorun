import { useEffect, useState } from 'react';

const PROVIDERS = [
  { key: 'kakao', label: '카카오로 시작하기' },
  { key: 'naver', label: '네이버로 시작하기' },
  { key: 'google', label: '구글로 시작하기' },
];

const ERROR_DISPLAY_MS = 5000;

// 소셜 로그인은 브라우저 전체 리다이렉트라 fetch가 아닌 페이지 이동으로 시작합니다.
const startLogin = (provider) => {
  window.location.href = `/api/v1/auth/${provider}`;
};

const Login = () => {
  const [error, setError] = useState(() => new URLSearchParams(window.location.search).get('error'));

  useEffect(() => {
    if (!error) return undefined;

    // 새로고침 시 에러가 다시 뜨지 않도록 쿼리스트링을 바로 지운다.
    window.history.replaceState(null, '', '/login');

    const timer = setTimeout(() => setError(null), ERROR_DISPLAY_MS);
    return () => clearTimeout(timer);
  }, [error]);

  return (
    <div className="login-page">
      <div className="login-card">
        <p className="login-eyebrow">두루런과 함께</p>
        <h1>바다를 따라, 나답게 달려요</h1>
        <p className="login-desc">소셜 계정으로 간편하게 시작해보세요</p>

        {error && <p className="login-error">{error}</p>}

        <div className="login-buttons">
          {PROVIDERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`social-button ${key}`}
              onClick={() => startLogin(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Login;
