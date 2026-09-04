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

// 코드리뷰 - "경계선 위 점"이 실제로 어떻게 판정되는지 확인
// 백엔드 shapely covers()는 경계 포함(inside), 이 셋은 백엔드와 그대로 일치.
const BOUNDARY_MATCH_CASES = [
  [38.61345573508535, 128.35615584937682, '외곽 링 변 위(꼭짓점 두 개의 정중앙)'],
  [37.74382897339144, 128.98191615064763, '구멍1 링 꼭짓점(정확히 그 점)'],
  [37.74418359723995, 128.98144838421598, '구멍1 링 변 위(꼭짓점 두 개의 정중앙)'],
];

// 실측 결과 백엔드와 유일하게 어긋나는 케이스:
// 실사용 버그로 보진 않지만, pointInPolygon.js를 나중에 고칠 때
// 이 케이스가 조용히 다른 방향으로 깨지지 않도록 false 그대로 기대값 고정.
const KNOWN_DIVERGENCE_CASES = [
  [38.61357533263314, 128.35715799005047, '외곽 링 꼭짓점(정확히 그 점) - 백엔드는 포함, 프론트는 제외'],
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
check(BOUNDARY_MATCH_CASES, true, 'boundary-match');
check(KNOWN_DIVERGENCE_CASES, false, 'known-divergence');

console.log(allPass ? '\n=== ALL PASS ===' : '\n=== SOME FAILED ===');
process.exit(allPass ? 0 : 1);
