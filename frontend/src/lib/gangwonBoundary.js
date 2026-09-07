import { apiFetch } from '../api';

// GET /v1/courses/gangwon-boundary로 강원도 경계 geojson을 받아와 캐싱.
// 도 경계는 거의 안 바뀌므로 세션 동안 한 번만 fetch하면 충분.
let boundaryPromise = null;

export const loadGangwonBoundary = () => {
  if (!boundaryPromise) {
    boundaryPromise = apiFetch('/v1/courses/gangwon-boundary')
      .then((res) => {
        if (!res.ok) throw new Error('강원도 경계 데이터를 불러오지 못했습니다.');
        return res.json();
      })
      .then((geojson) => geojson.geometry)
      .catch((err) => {
        boundaryPromise = null; // 실패하면 다음 호출 때 재시도
        throw err;
      });
  }
  return boundaryPromise;
};
