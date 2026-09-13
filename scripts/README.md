# scripts/

Helper utilities for testing and schema introspection.

- **`dump_schema.py`** — Runs a full GraphQL introspection query against the Octopus Energy Japan endpoint and saves the schema locally for inspection.
- **`test_login.py`** — Tests the full API call chain (login, account retrieval, supply point discovery, and half-hourly usage readings) using `custom_components/octopus_energy_jp/api.py`, without requiring a running Home Assistant instance.

### Dependencies

Both scripts only require `aiohttp` (`pip install aiohttp`).
