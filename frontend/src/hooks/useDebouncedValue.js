import { useEffect, useState } from 'react';

// 값이 delay(ms) 동안 안 바뀌면 그때 갱신된 값을 반환 (입력창 타이핑마다 API 호출되는 것 방지)
export const useDebouncedValue = (value, delay = 400) => {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
};
