"""Constants for the Octopus Energy Japan integration."""

DOMAIN = "octopus_energy_jp"

CONF_ACCOUNT_NUMBER = "account_number"

# Kraken JWT 有效期一般为 60 分钟，这里留出安全余量提前刷新
TOKEN_ASSUMED_LIFETIME_MINUTES = 55

DEFAULT_SCAN_INTERVAL_MINUTES = 30

# 第一次设置集成时，如果 Energy Dashboard 长期统计里还没有任何数据，
# 就往前回填这么多天的半小时用电量（聚合成整点小时后写入）。
# Kraken 那边具体能查到多久之前的数据以实际返回为准，这里只是请求的上限。
STATISTICS_BACKFILL_DAYS = 30

GRAPHQL_URL = "https://api.oejp-kraken.energy/v1/graphql/"

