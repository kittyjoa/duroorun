"""강원도 실제 경계(폴리곤) 데이터를 만드는 1회성 추출 스크립트.

ㅡ 원본: 국가데이터처 SGIS "행정구역 통계 및 경계_20250630"의 시도 경계 shapefile
  (2025년 2분기 시도 경계 기준, 이용허락범위 제한 없음)
  https://www.data.go.kr/data/15129688/fileData.do
ㅡ 좌표계가 EPSG:5179(Korea 2000 / Unified CS, 미터 단위)라서 우리가 쓰는
  위경도(EPSG:4326, WGS84)로 재투영 필요. .prj 파일로 원본 좌표계 확인함.
ㅡ 강원도(SIDO_CD=32) 본토(외곽 1개 + 구멍 2개)만 남김.
  구멍 2개는 카카오맵으로 좌표 확인 결과 둘 다 물이라 실사용 영향 X
ㅡ 본토 링 30m 이내 굴곡을 정리해 정확도 손실 거의 없이 파일 크기를 줄임.
ㅡ 원본 shapefile(5개 파일, 83MB)은 런타임에 안 쓰여서 git/Docker 이미지에 안 올림
ㅡ 재실행 방법: pip install pyshp pyproj
  python -m app.scripts.extract_gangwon_boundary
ㅡ 도 경계는 거의 바뀌지 않아 유지/보수 어렵지 않음
"""

import json
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely.geometry.polygon import orient

_DATA_DIR = Path(__file__).parent.parent / "domain" / "course" / "gangwon_boundary"
_SOURCE_SHP_PATH = _DATA_DIR / "bnd_sido_00_2025_2Q.shp"
_OUTPUT_PATH = _DATA_DIR / "gangwon_boundary.geojson"

_GANGWON_SIDO_CD = "32"
_SOURCE_CRS = "EPSG:5179"  # 원본 shapefile 좌표계
_TARGET_CRS = "EPSG:4326"  # 앱에서 쓰는 좌표계
_SIMPLIFY_TOLERANCE_METERS = 30  # 굴곡 정리해 파일 크기 줄임


def _find_mainland_rings(shp_path: Path, sido_cd: str) -> list[list[tuple[float, float]]]:
    """지정한 시도의 조각(polygon) 중 점 개수가 가장 많은(=본토) 것의 링들을 반환."""
    sf = shapefile.Reader(str(shp_path), encoding="utf-8")
    idx = next(i for i, rec in enumerate(sf.records()) if rec["SIDO_CD"] == sido_cd)
    geo = sf.shapeRecord(idx).shape.__geo_interface__
    # "Polygon" 타입이면 coordinates가 링 목록 하나뿐이라 감싸줘야 함(섬 없는 시도 대비)
    polygons = [geo["coordinates"]] if geo["type"] == "Polygon" else geo["coordinates"]
    return max(polygons, key=lambda poly: len(poly[0]))


def extract_gangwon_boundary() -> dict:
    mainland_rings = _find_mainland_rings(_SOURCE_SHP_PATH, _GANGWON_SIDO_CD)
    exterior_raw, *holes_raw = mainland_rings

    # Douglas-Peucker 알고리즘 사용
    # 순서: 원본 미터단위 좌표계에서 30미터 단순화 먼저 → 앱에서 쓰는 위경도 좌표계로 재투영
    polygon = Polygon(exterior_raw, holes=holes_raw)
    simplified = polygon.simplify(_SIMPLIFY_TOLERANCE_METERS, preserve_topology=True)

    transformer = Transformer.from_crs(_SOURCE_CRS, _TARGET_CRS, always_xy=True)

    def reproject_ring(coords: list[tuple[float, float]]) -> list[list[float]]:
        return [list(transformer.transform(x, y)) for x, y in coords]

    reprojected = Polygon(
        reproject_ring(list(simplified.exterior.coords)),
        holes=[reproject_ring(list(interior.coords)) for interior in simplified.interiors],
    )
    # GeoJSON 권장 방향(외곽 반시계, 구멍 시계)으로 정규화
    normalized = orient(reprojected, sign=1.0)

    return {
        "type": "Feature",
        "properties": {
            "name": "강원특별자치도",
            "code": _GANGWON_SIDO_CD,
            "source": (
                "국가데이터처 SGIS 행정구역 통계 및 경계_20250630 "
                "(2025년 2분기 기준), 이용허락범위 제한 없음"
            ),
        },
        "geometry": mapping(normalized),
    }


if __name__ == "__main__":
    feature = extract_gangwon_boundary()
    _OUTPUT_PATH.write_text(json.dumps(feature, ensure_ascii=False), encoding="utf-8")
    print(f"saved: {_OUTPUT_PATH} ({_OUTPUT_PATH.stat().st_size} bytes)")
