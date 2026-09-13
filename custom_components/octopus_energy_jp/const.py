"""Constants for the Octopus Energy Japan integration."""

DOMAIN = "octopus_energy_jp"

CONF_ACCOUNT_NUMBER = "account_number"

# Kraken JWT tokens are typically valid for 60 minutes; refresh a bit early
# to be safe.
TOKEN_ASSUMED_LIFETIME_MINUTES = 55

DEFAULT_SCAN_INTERVAL_MINUTES = 30

# Lookback window used to find the "latest half-hourly reading". Kraken's
# smart meter data reporting is delayed, so a short window often returns
# nothing. 3 days covers the delay and is also enough to compute "today's
# usage".
LATEST_READING_LOOKBACK_HOURS = 72

# Note: Account.balance/overdueBalance and bill amounts do NOT need to be
# divided by 100. The Japanese Kraken instance stores plain yen values,
# unlike the GBP instance's minor-unit convention (verified against a real
# bill: ¥5787 paid, API returned 5787).

# On first setup, if the Energy Dashboard long-term statistics table is
# still empty, backfill this many days of half-hourly usage (aggregated
# into hourly buckets). Querying beyond the actual data range just returns
# an empty list rather than an error, so this is set generously to 2 years;
# backfilling must be chunked (see STATISTICS_BACKFILL_CHUNK_DAYS below),
# otherwise data is silently dropped.
STATISTICS_BACKFILL_DAYS = 730

# Discovered the hard way: `halfHourlyReadings` silently truncates results
# when the requested time span is too large (no error) -- the same 400-day
# range returned only 1476 readings in one request but 2708 when split into
# 7-day chunks. Historical backfills must be chunked by this many days
# instead of requesting the whole STATISTICS_BACKFILL_DAYS range at once.
STATISTICS_BACKFILL_CHUNK_DAYS = 7

# Fetch this many recent bills (invoices/statements) alongside each account
# refresh, for display purposes.
BILLS_FETCH_COUNT = 5

GRAPHQL_URL = "https://api.oejp-kraken.energy/v1/graphql/"
