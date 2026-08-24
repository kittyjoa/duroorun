import { createContext, useContext, useEffect, useState } from 'react';

import { apiFetch, getAccessToken } from '../api';

const UserContext = createContext(null);

// 로그인한 유저 정보를 앱 전체가 공유하는 곳. Header/MyPage가 각자 따로
// /users/me를 불러오면 한쪽에서 수정해도 다른 쪽엔 반영이 안 되는 문제가 있어서,
// 여기 하나로 모아 setUser()만 부르면 이걸 구독하는 모든 컴포넌트가 같이 갱신되게 한다.
export const UserProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  const refreshUser = async () => {
    if (!getAccessToken()) {
      setUser(null);
      setHasError(false);
      setIsLoading(false);
      return null;
    }

    try {
      const res = await apiFetch('/v1/users/me');
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        setHasError(false);
        return data;
      }
      // apiFetch가 401은 이미 내부에서 재발급 재시도까지 해봤으므로, 그래도 401이면 진짜 로그아웃 상태.
      // 5xx 등 다른 실패는 일시적 오류로 보고 user를 그대로 둔다 (로그인 상태를 함부로 지우지 않음).
      if (res.status === 401) {
        setUser(null);
        setHasError(false);
      } else {
        setHasError(true);
      }
      return null;
    } catch {
      // 네트워크 오류도 인증 실패로 단정하지 않음
      setHasError(true);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    refreshUser();
  }, []);

  return (
    <UserContext.Provider value={{ user, setUser, refreshUser, isLoading, hasError }}>
      {children}
    </UserContext.Provider>
  );
};

export const useUser = () => useContext(UserContext);
