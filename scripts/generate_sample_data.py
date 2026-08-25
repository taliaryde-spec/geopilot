"""Generate deterministic fictional datasets for the GeoPilot demo."""

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA_DIR = PROJECT_ROOT / "examples" / "data"


def build_facilities() -> gpd.GeoDataFrame:
    """Return fictional public-service facilities around central Shanghai."""
    return gpd.GeoDataFrame(
        {
            "facility_id": ["F001", "F002", "F003", "F004", "F005"],
            "name": [
                "惠民社区卫生服务站",
                "晨光小学",
                "城市阅读空间",
                "邻里运动中心",
                "长青养老服务站",
            ],
            "category": [
                "clinic",
                "school",
                "library",
                "sports_center",
                "elderly_care",
            ],
            "capacity": [80, 600, 120, 300, 90],
            "service_radius_m": [1000, 1000, 1000, 1000, 1000],
        },
        geometry=[
            Point(121.439, 31.219),
            Point(121.441, 31.221),
            Point(121.460, 31.220),
            Point(121.440, 31.240),
            Point(121.480, 31.250),
        ],
        crs="EPSG:4326",
    )


def build_neighborhoods() -> gpd.GeoDataFrame:
    """Return four fictional residential areas used by the coverage demo."""
    return gpd.GeoDataFrame(
        {
            "neighborhood_id": ["N001", "N002", "N003", "N004"],
            "name": ["春华片区", "江景片区", "书院片区", "新城片区"],
            "population": [8200, 11600, 7400, 15300],
            "demand_score": [0.45, 0.62, 0.51, 0.91],
        },
        geometry=[
            box(121.437, 31.217, 121.443, 31.223),
            box(121.457, 31.217, 121.463, 31.223),
            box(121.437, 31.237, 121.443, 31.243),
            box(121.457, 31.237, 121.463, 31.243),
        ],
        crs="EPSG:4326",
    )


def main() -> None:
    """Write all demo datasets to the examples directory."""
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    facilities = build_facilities()
    neighborhoods = build_neighborhoods()
    datasets = {
        "facilities.geojson": facilities,
        "neighborhoods.geojson": neighborhoods,
    }
    for filename, frame in datasets.items():
        output_path = SAMPLE_DATA_DIR / filename
        frame.to_file(output_path, driver="GeoJSON", index=False)
        print(f"Generated {output_path.relative_to(PROJECT_ROOT)}")

    csv_frame = facilities.drop(columns=facilities.geometry.name).copy()
    csv_frame["longitude"] = facilities.geometry.x
    csv_frame["latitude"] = facilities.geometry.y
    csv_path = SAMPLE_DATA_DIR / "facilities.csv"
    csv_frame.to_csv(
        csv_path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
    )
    print(f"Generated {csv_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
