// 표준 ray-casting(짝수-홀수 규칙)으로 점이 GeoJSON 링 안에 있는지 판정
// coords: [[lng, lat], ...] - GeoJSON 좌표 순서(경도, 위도) 그대로 받음
const _isPointInRing = (lng, lat, coords) => {
  let inside = false;
  for (let i = 0, j = coords.length - 1; i < coords.length; j = i++) {
    const [xi, yi] = coords[i];
    const [xj, yj] = coords[j];
    const crosses = yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
};

// GeoJSON Polygon geometry(coordinates: [외곽 링, 구멍 링...]) 안에 점이 있는지 판정
// - 외곽 링 안쪽 + 모든 구멍 링 바깥쪽 → 폴리곤 안으로 인정
// - course/schemas.py의 _in_gangwon(shapely covers())과 같은 판정 로직을
//   서버 요청 없이 프론트에서도 쓰기 위한 용도
//   (경계선 위 점 처리 등 극히 드문 경우만 미세하게 다를 수 있음)
export const isPointInPolygon = (point, polygonGeometry) => {
  const [exterior, ...holes] = polygonGeometry.coordinates;
  if (!_isPointInRing(point.lng, point.lat, exterior)) return false;
  return !holes.some((hole) => _isPointInRing(point.lng, point.lat, hole));
};
