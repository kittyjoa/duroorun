"""강원도 18개 시군구 경계(폴리곤) 데이터를 만드는 1회성 추출 스크립트.

ㅡ extract_gangwon_boundary.py(강원도 전체 외곽선 추출)와 같은 방식이지만,
  시군구 단위로 쪼개서 커스텀 코스 좌표(위경도)가 어느 시군에 속하는지
  판별하는 데 씀 (카카오 등 외부 지오코딩 API 호출 없이 로컬에서 처리).
ㅡ 원본: 국가데이터처 SGIS "행정구역 통계 및 경계_20250630"의 시군구 경계 shapefile
  (2025년 2분기 기준, 이용허락범위 제한 없음)
  https://www.data.go.kr/data/15129688/fileData.do
ㅡ 좌표계가 EPSG:5179(Korea 2000 / Unified CS, 미터 단위)라서 우리가 쓰는
  위경도(EPSG:4326, WGS84)로 재투영 필요.
ㅡ SIGUNGU_CD가 "32"로 시작하는 레코드만 강원도. 섬 등으로 폴리곤이 여러
  조각이어도(MultiPolygon) 판별 정확도를 위해 전부 보존함 (본토만 남기지 않음).
ㅡ 각 시군구 링을 30m 이내 굴곡 정리해 정확도 손실 거의 없이 파일 크기를 줄임.
ㅡ 원본 shapefile(5개 파일)은 런타임에 안 쓰여서 git/Docker 이미지에 안 올림
ㅡ 재실행 방법: pip install pyshp pyproj shapely
  python -m app.scripts.extract_gangwon_sigungu_boundary
ㅡ 시군구 경계는 거의 바뀌지 않아 유지/보수 어렵지 않음
"""

import json
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

_DATA_DIR = Path(__file__).parent.parent / "domain" / "course" / "gangwon_boundary"
_SOURCE_SHP_PATH = _DATA_DIR / "bnd_sigungu_00_2025_2Q.shp"
_OUTPUT_PATH = _DATA_DIR / "gangwon_sigungu_boundary.geojson"

_GANGWON_SIDO_PREFIX = "32"
_SOURCE_CRS = "EPSG:5179"  # 원본 shapefile 좌표계
_TARGET_CRS = "EPSG:4326"  # 앱에서 쓰는 좌표계
_SIMPLIFY_TOLERANCE_METERS = 30  # 굴곡 정리해 파일 크기 줄임


def extract_gangwon_sigungu_boundary() -> dict:
    sf = shapefile.Reader(str(_SOURCE_SHP_PATH), encoding="utf-8")
    transformer = Transformer.from_crs(_SOURCE_CRS, _TARGET_CRS, always_xy=True)

    features = []
    for shape_record in sf.shapeRecords():
        record = shape_record.record
        if not record["SIGUNGU_CD"].startswith(_GANGWON_SIDO_PREFIX):
            continue

        geom = shape(shape_record.shape.__geo_interface__)
        simplified = geom.simplify(_SIMPLIFY_TOLERANCE_METERS, preserve_topology=True)
        reprojected = shapely_transform(transformer.transform, simplified)

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "code": record["SIGUNGU_CD"],
                    "name": record["SIGUNGU_NM"],
                },
                "geometry": mapping(reprojected),
            }
        )

    features.sort(key=lambda f: f["properties"]["code"])
    return {
        "type": "FeatureCollection",
        "properties": {
            "source": (
                "국가데이터처 SGIS 행정구역 통계 및 경계_20250630 "
                "(2025년 2분기 기준), 이용허락범위 제한 없음"
            ),
        },
        "features": features,
    }


if __name__ == "__main__":
    collection = extract_gangwon_sigungu_boundary()
    _OUTPUT_PATH.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    feature_count = len(collection["features"])
    print(f"saved: {_OUTPUT_PATH} ({_OUTPUT_PATH.stat().st_size} bytes, {feature_count}개 시군구)")
