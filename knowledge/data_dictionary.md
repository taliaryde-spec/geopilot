# GeoPilot 示例数据字典

本文档定义 `examples/data` 下虚构演示数据的字段含义。字段说明只适用于 GeoPilot 示例，不应自动套用到用户上传的其他数据。

## facilities.csv 设施点

每行代表一个虚构公共服务设施。CSV 通过经纬度字段转换为 EPSG:4326 点几何。

| 字段 | 类型 | 含义 |
|---|---|---|
| `facility_id` | 字符串 | 设施唯一标识 |
| `name` | 字符串 | 设施名称 |
| `category` | 字符串 | 设施类别 |
| `capacity` | 整数 | 示例服务容量，仅作为属性保留，当前覆盖率公式不使用 |
| `service_radius_m` | 数值 | 欧氏直线服务半径，单位为米，必须大于零 |
| `longitude` | 数值 | WGS 84 经度，作为点几何 X 坐标 |
| `latitude` | 数值 | WGS 84 纬度，作为点几何 Y 坐标 |

设施表没有 `neighborhood_id` 字段。设施属于哪个社区需要通过点与社区面的空间关系计算，不能依赖属性连接猜测。

## neighborhoods.geojson 社区面

每个要素代表一个虚构社区多边形，原始 CRS 为 EPSG:4326。

| 字段 | 类型 | 含义 |
|---|---|---|
| `neighborhood_id` | 字符串 | 社区唯一标识，是覆盖指标和设施计数的连接键 |
| `name` | 字符串 | 社区名称 |
| `population` | 整数 | 社区总人口，用于面积加权覆盖人口估算 |
| `demand_score` | 数值 | 虚构需求评分，当前覆盖率计算不直接使用，可用于后续选址排序 |

`neighborhood_area_m2` 不是原始字段。该字段必须在 EPSG:32651 等适用米制投影下，由完整社区几何计算得到，不能在 EPSG:4326 中直接计算平方米面积。

## 分析派生字段

| 字段 | 来源 | 含义 |
|---|---|---|
| `intersection_area_m2` | 社区与融合缓冲区求交 | 社区内部被覆盖的面积，单位平方米 |
| `coverage_ratio` | 覆盖面积除以社区总面积 | 覆盖率，合法范围为零到一 |
| `estimated_covered_population` | `population * coverage_ratio` | 均匀人口密度假设下的估算覆盖人口 |
| `facility_count` | 社区面与设施点空间连接 | 位于或接触社区边界的设施点数量 |

派生字段应由确定性 GIS 工具生成并通过验证。语言模型可以解释字段，但不能编造字段值。
