const PROVIDERS = [
  { key: 'kakao', label: '카카오로 시작하기' },
  { key: 'naver', label: '네이버로 시작하기' },
  { key: 'google', label: '구글로 시작하기' },
];

// 소셜 로그인은 브라우저 전체 리다이렉트라 fetch가 아닌 페이지 이동으로 시작합니다.
const startLogin = (provider) => {
  window.location.href = `/api/v1/auth/${provider}`;
};

const Login = () => {
  return (
    <div className="login-page">
      <div className="login-card">
        <p className="login-eyebrow">두루런과 함께</p>
        <h1>바다를 따라, 나답게 달려요</h1>
        <p className="login-desc">소셜 계정으로 간편하게 시작해보세요</p>

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
