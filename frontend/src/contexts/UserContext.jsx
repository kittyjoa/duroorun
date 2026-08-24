import { createContext, useContext, useEffect, useState } from 'react';

import { apiFetch, getAccessToken } from '../api';

const UserContext = createContext(null);

// 로그인한 유저 정보를 앱 전체가 공유하는 곳. Header/MyPage가 각자 따로
// /users/me를 불러오면 한쪽에서 수정해도 다른 쪽엔 반영이 안 되는 문제가 있어서,
// 여기 하나로 모아 setUser()만 부르면 이걸 구독하는 모든 컴포넌트가 같이 갱신되게 한다.
export const UserProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshUser = async () => {
    if (!getAccessToken()) {
      setUser(null);
      setIsLoading(false);
      return null;
    }

    try {
      const res = await apiFetch('/v1/users/me');
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        return data;
      }
      setUser(null);
      return null;
    } catch {
      setUser(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    refreshUser();
  }, []);

  return (
    <UserContext.Provider value={{ user, setUser, refreshUser, isLoading }}>
      {children}
    </UserContext.Provider>
  );
};

export const useUser = () => useContext(UserContext);
