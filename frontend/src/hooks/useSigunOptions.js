import { useEffect, useState } from 'react';

import { apiFetch } from '../api';

// 코스 지역 필터 드롭다운 옵션
// ㅡ 실제로 코스가 존재하는 시군만 서버에서 동적으로 받아옴
// ㅡ DRNB/CUSTOM 공용 훅
export const useSigunOptions = (path) => {
  const [options, setOptions] = useState([]);

  useEffect(() => {
    let ignore = false;
    apiFetch(path)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data) setOptions(data.items);
      })
      .catch(() => {}); // 옵션 로딩 실패해도 "지역 전체"만 있는 드롭다운으로 동작은 가능
    return () => {
      ignore = true;
    };
  }, [path]);

  return options;
};
