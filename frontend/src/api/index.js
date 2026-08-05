const REFRESH_ENDPOINT = '/v1/auth/refresh';

const getAccessToken = () => localStorage.getItem('accessToken');
const setAccessToken = (token) => localStorage.setItem('accessToken', token);
const clearAccessToken = () => localStorage.removeItem('accessToken');

const buildRequest = (options, accessToken) => ({
  ...options,
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
    ...(accessToken && { Authorization: `Bearer ${accessToken}` }),
    ...options.headers,
  },
});

const refreshAccessToken = async () => {
  const res = await fetch(`/api${REFRESH_ENDPOINT}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    clearAccessToken();
    return null;
  }
  const data = await res.json();
  setAccessToken(data.access_token);
  return data.access_token;
};

// 401 응답 시 Refresh Token으로 재발급 후 원요청을 한 번만 재시도합니다.
export const apiFetch = async (url, options = {}) => {
  let accessToken = getAccessToken();
  let res = await fetch(`/api${url}`, buildRequest(options, accessToken));

  if (res.status === 401 && url !== REFRESH_ENDPOINT) {
    accessToken = await refreshAccessToken();
    if (accessToken) {
      res = await fetch(`/api${url}`, buildRequest(options, accessToken));
    }
  }

  return res;
};

export { getAccessToken, setAccessToken, clearAccessToken };
