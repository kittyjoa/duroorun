import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiFetch } from '../api';

const Onboarding = () => {
  const [nickname, setNickname] = useState('');
  const [location, setLocation] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);

    const res = await apiFetch('/v1/users/me', {
      method: 'PUT',
      body: JSON.stringify({ nickname, location }),
    });

    setSubmitting(false);

    if (!res.ok) {
      const data = await res.json().catch(() => null);
      setError(data?.detail ?? '가입 완료 중 오류가 발생했어요');
      return;
    }

    navigate('/', { replace: true });
  };

  return (
    <div className="onboarding-page">
      <form className="onboarding-card" onSubmit={handleSubmit}>
        <h1>거의 다 왔어요!</h1>
        <p className="onboarding-desc">두루런에서 쓸 닉네임과 거주지를 알려주세요</p>

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

        <button type="submit" className="primary-button" disabled={submitting}>
          {submitting ? '처리 중...' : '시작하기'}
        </button>
      </form>
    </div>
  );
};

export default Onboarding;
