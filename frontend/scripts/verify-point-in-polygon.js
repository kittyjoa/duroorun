/**
 * pointInPolygon.js가 백엔드와 같은 판정을 내리는지 확인하는 1회성 검증 스크립트.
 *
 * ㅡ 프론트가 직접 구현한 ray-casting이 백엔드의 shapely covers() 판정과 어긋나지 않는지,
 *   tests/test_course_custom.py에 있는 것과 같은 좌표들로 재확인하는 용도
 * ㅡ vite 빌드/번들에는 안 들어감(아무 데서도 import 안 함): 수동 실행 전용
 * ㅡ 실행 방법: node frontend/scripts/verify-point-in-polygon.js
 * ㅡ 순수 함수인 pointInPolygon만 대상
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { isPointInPolygon } from '../src/lib/pointInPolygon.js';

const _dirname = path.dirname(fileURLToPath(import.meta.url));
const boundaryPath = path.resolve(
  _dirname,
  '../../app/domain/course/gangwon_boundary/gangwon_boundary.geojson',
);
const { geometry } = JSON.parse(readFileSync(boundaryPath, 'utf-8'));

// test_course_custom.py의 test_waypoint_accepts/rejects_gangwon_coords와 같은 좌표
const ACCEPT_CASES = [
  [37.7519, 128.8761, '강릉시청'],
  [38.207, 128.5918, '속초해변'],
  [37.3422, 127.9202, '원주시청'],
  [38.1462, 127.3097, '철원 - 실제 경계엔 자연히 포함됨'],
];

const REJECT_CASES = [
  [37.5, 127.5, '코드리뷰 반례 - 예전 사각형 박스는 통과시켰지만 실제 강원도는 아님'],
  [37.5, 129.3, '동해 바다 한가운데 - 예전 박스 안이지만 육지가 아님'],
  [37.7, 127.45, '경기 가평 인근 - 예전 박스 안이지만 강원도 아님'],
  [37.0, 129.2, '경북 울진 인근 - 예전 박스 안이지만 강원도 아님'],
];

// 강원도 경계 폴리곤의 구멍 2개(물) 중심 - 안쪽으로 판정되면 안 됨
const HOLE_CASES = [
  [37.744401, 128.981835, '구멍1(수역)'],
  [37.438091, 129.18947, '구멍2(수역)'],
];

let allPass = true;

const check = (cases, expected, label) => {
  for (const [lat, lng, desc] of cases) {
    const result = isPointInPolygon({ lat, lng }, geometry);
    const pass = result === expected;
    if (!pass) allPass = false;
    console.log(`[${label}] ${desc} (${lat}, ${lng}) -> ${result} ${pass ? 'OK' : 'FAIL'}`);
  }
};

check(ACCEPT_CASES, true, 'accept');
check(REJECT_CASES, false, 'reject');
check(HOLE_CASES, false, 'hole');

console.log(allPass ? '\n=== ALL PASS ===' : '\n=== SOME FAILED ===');
process.exit(allPass ? 0 : 1);
