"""DataUpdateCoordinator for Octopus Energy Japan.

Besides providing sensor.py with real-time display data (e.g. "latest
half-hourly reading"/"account balance"), this also aggregates half-hourly
readings into hourly buckets and writes them to Home Assistant's long-term
statistics table (homeassistant.components.recorder.statistics), so users
can select this integration as a "grid consumption" source under Settings
-> Dashboards -> Energy, with automatic historical backfill on first run.
The approach follows the `opower` integration bundled with HA core (an
official integration of the same kind that pulls usage data from a power
company).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.const import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # Fallback for older HA versions without StatisticMeanType
    StatisticMeanType = None  # type: ignore[assignment,misc]

_MEAN_TYPE_NONE = StatisticMeanType.NONE if StatisticMeanType is not None else None

from .api import OctopusJapanApiClient, OctopusJapanApiError
from .const import (
    BILLS_FETCH_COUNT,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    LATEST_READING_LOOKBACK_HOURS,
    STATISTICS_BACKFILL_CHUNK_DAYS,
    STATISTICS_BACKFILL_DAYS,
)

_LOGGER = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("_", value.lower()).strip("_")


def start_of_local_week(reference: datetime | None = None) -> datetime:
    """Start of "this week" in the local timezone (Monday 00:00).

    `sensor.py` uses this same function for the `last_reset` of This
    Week's Consumption/Cost, so the boundary matches exactly what the
    coordinator uses when querying long-term statistics.
    """
    today = dt_util.start_of_local_day(reference)
    return today - timedelta(days=today.weekday())


def start_of_local_month(reference: datetime | None = None) -> datetime:
    """Start of "this month" in the local timezone (the 1st, 00:00)."""
    today = dt_util.start_of_local_day(reference)
    return today.replace(day=1)


class OctopusJapanDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Periodically fetches account info, writes long-term statistics, and
    provides recent readings for sensors to display."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: OctopusJapanApiClient,
        account_number: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Octopus Energy Japan",
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        self._client = client
        self.account_number = account_number
        self._account_slug = _slugify(account_number)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            account = await self._client.async_get_account(self.account_number)
        except OctopusJapanApiError as err:
            raise UpdateFailed(str(err)) from err

        total_consumption_kwh = 0.0
        total_cost_jpy = 0.0
        try:
            spin_sums = await self._async_insert_statistics(account)
            for consumption_sum, cost_sum in spin_sums.values():
                total_consumption_kwh += consumption_sum
                total_cost_jpy += cost_sum
            # Also backfill history for the Total Consumption/Total Cost
            # sensor entities' own long-term statistics, not just the
            # external statistic_id -- this way, whether the user picks the
            # entity or the external statistic in the Energy Dashboard, the
            # history is equally complete and matches the official app's
            # usage/cost (see `_async_sync_entity_level_statistics`).
            await self._async_sync_entity_level_statistics()
        except OctopusJapanApiError as err:
            # A failure importing Energy Dashboard statistics shouldn't
            # crash the whole coordinator; just log a warning, it will
            # retry on the next refresh.
            _LOGGER.warning("Failed to import Energy Dashboard long-term statistics: %s", err)

        now = datetime.now(timezone.utc)
        try:
            readings_by_spin = await self._client.async_get_electricity_half_hourly(
                self.account_number,
                now - timedelta(hours=LATEST_READING_LOOKBACK_HOURS),
                now,
            )
        except OctopusJapanApiError as err:
            raise UpdateFailed(str(err)) from err

        all_readings = [r for readings in readings_by_spin.values() for r in readings]
        all_readings.sort(key=lambda r: r.get("startAt") or "")
        latest_reading = all_readings[-1] if all_readings else None

        today_start = dt_util.start_of_local_day()
        today_consumption_kwh = 0.0
        today_cost_jpy = 0.0
        for reading in all_readings:
            start_at = reading.get("startAt")
            if not start_at:
                continue
            reading_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            if reading_dt >= today_start:
                today_consumption_kwh += float(reading.get("value") or 0)
                today_cost_jpy += float(reading.get("costEstimate") or 0)

        # This Week's / This Month's usage and cost: don't re-query Kraken,
        # read directly from HA's own long-term statistics table (kept up
        # to date by `_async_insert_statistics` on every refresh) and sum
        # by hour. No extra API cost, and no risk of Kraken silently
        # truncating a large-range query. Like Today's Consumption, the
        # last hour or two may be missing due to meter reporting delay --
        # that's expected.
        consumption_stat_ids = {
            f"{DOMAIN}:{self._account_slug}_{_slugify(spin)}_consumption"
            for spin in self._get_spins(account)
        }
        cost_stat_ids = {
            f"{DOMAIN}:{self._account_slug}_{_slugify(spin)}_cost"
            for spin in self._get_spins(account)
        }
        week_start = start_of_local_week()
        month_start = start_of_local_month()
        week_consumption_kwh = await self._async_get_period_total(
            consumption_stat_ids, week_start
        )
        week_cost_jpy = await self._async_get_period_total(cost_stat_ids, week_start)
        month_consumption_kwh = await self._async_get_period_total(
            consumption_stat_ids, month_start
        )
        month_cost_jpy = await self._async_get_period_total(cost_stat_ids, month_start)

        try:
            bills = await self._client.async_get_bills(
                self.account_number, first=BILLS_FETCH_COUNT
            )
        except OctopusJapanApiError as err:
            # A bills API failure shouldn't crash the whole coordinator;
            # keep the previous bills data (if any) and log a warning.
            _LOGGER.warning("Failed to fetch bills: %s", err)
            bills = self.data.get("bills", []) if self.data else []

        primary_supply_point = self._primary_supply_point(account)

        return {
            "account": account,
            "account_status": account.get("status"),
            "primary_supply_point": primary_supply_point,
            "bills": bills,
            "latest_reading": latest_reading,
            "today_consumption_kwh": today_consumption_kwh,
            "today_cost_jpy": today_cost_jpy,
            "week_consumption_kwh": week_consumption_kwh,
            "week_cost_jpy": week_cost_jpy,
            "month_consumption_kwh": month_consumption_kwh,
            "month_cost_jpy": month_cost_jpy,
            "total_consumption_kwh": total_consumption_kwh,
            "total_cost_jpy": total_cost_jpy,
        }

    def _primary_supply_point(self, account: dict[str, Any]) -> dict[str, Any] | None:
        """Take the first electricitySupplyPoint of the first property as
        the "primary meter".

        Only verified against a real account with a single property/single
        meter; for multi-property/multi-meter cases this only shows the
        first one, matching the known limitation noted in the README.
        """
        for prop in account.get("properties") or []:
            for supply_point in prop.get("electricitySupplyPoints") or []:
                return supply_point
        return None

    def _get_spins(self, account: dict[str, Any]) -> list[str]:
        spins: list[str] = []
        for prop in account.get("properties") or []:
            for sp in prop.get("electricitySupplyPoints") or []:
                spin = sp.get("spin")
                if spin and spin not in spins:
                    spins.append(spin)
        return spins

    async def _async_insert_statistics(
        self, account: dict[str, Any]
    ) -> dict[str, tuple[float, float]]:
        """Write long-term statistics for each meter (spin), and return
        {spin: (cumulative consumption kWh, cumulative cost JPY)}.

        The return value is also the authoritative source for "how much
        power/money has been used so far", used directly by the Total
        Consumption / Total Cost sensors in sensor.py
        (state_class=TOTAL_INCREASING), avoiding a second calculation.
        """
        result: dict[str, tuple[float, float]] = {}
        for spin in self._get_spins(account):
            result[spin] = await self._async_insert_statistics_for_spin(spin)
        return result

    def _build_metadata(
        self, statistic_id: str, name: str, unit: str
    ) -> StatisticMetaData:
        metadata: dict[str, Any] = {
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": None,
            "unit_of_measurement": unit,
        }
        if _MEAN_TYPE_NONE is not None:
            metadata["mean_type"] = _MEAN_TYPE_NONE
        else:
            metadata["has_mean"] = False
        return metadata  # type: ignore[return-value]

    async def _async_insert_statistics_for_spin(self, spin: str) -> tuple[float, float]:
        spin_slug = _slugify(spin)
        consumption_stat_id = f"{DOMAIN}:{self._account_slug}_{spin_slug}_consumption"
        cost_stat_id = f"{DOMAIN}:{self._account_slug}_{spin_slug}_cost"

        consumption_metadata = self._build_metadata(
            consumption_stat_id, f"Octopus Energy Japan {spin} Consumption", "kWh"
        )
        cost_metadata = self._build_metadata(
            cost_stat_id, f"Octopus Energy Japan {spin} Cost", "JPY"
        )

        consumption_sum, start = await self._async_get_resume_point(consumption_stat_id)
        cost_sum, _ = await self._async_get_resume_point(cost_stat_id)

        end = datetime.now(timezone.utc)
        if start >= end:
            # No new hourly bucket to backfill, but the existing cumulative
            # value is still valid and must be returned to the caller (the
            # Total Consumption/Cost sensors need it).
            return consumption_sum, cost_sum

        hourly = await self._async_fetch_hourly_buckets(start, end, spin=spin)
        if not hourly:
            return consumption_sum, cost_sum

        consumption_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []
        for hour_start in sorted(hourly):
            bucket = hourly[hour_start]
            consumption_sum += bucket["value"]
            cost_sum += bucket["cost"]
            consumption_stats.append(
                StatisticData(
                    start=hour_start, state=bucket["value"], sum=consumption_sum
                )
            )
            cost_stats.append(
                StatisticData(start=hour_start, state=bucket["cost"], sum=cost_sum)
            )

        if consumption_stats:
            _LOGGER.debug(
                "Writing %s consumption statistics to %s", len(consumption_stats), consumption_stat_id
            )
            async_add_external_statistics(self.hass, consumption_metadata, consumption_stats)
        if cost_stats:
            _LOGGER.debug("Writing %s cost statistics to %s", len(cost_stats), cost_stat_id)
            async_add_external_statistics(self.hass, cost_metadata, cost_stats)

        return consumption_sum, cost_sum

    async def _async_fetch_hourly_buckets(
        self, start: datetime, end: datetime, *, spin: str | None = None
    ) -> dict[datetime, dict[str, float]]:
        """Query half-hourly readings in chunks of STATISTICS_BACKFILL_CHUNK_DAYS
        days, aggregating into hourly {value, cost} buckets.

        `spin` of None sums readings across **all meters** (used by the
        Total Consumption/Cost entities that aggregate across meters);
        passing a specific `spin` only counts that one meter (used by the
        per-spin external statistics).

        Must be chunked: `halfHourlyReadings` silently truncates results
        (no error) when the requested time span is too large (verified:
        the same 400-day range returned only 1476 readings in one request,
        but 2708 when split into 7-day chunks). Day-to-day incremental
        refreshes cover a small span and effectively only run one loop
        iteration, so there's no extra overhead.
        """
        hourly: dict[datetime, dict[str, float]] = {}
        chunk_delta = timedelta(days=STATISTICS_BACKFILL_CHUNK_DAYS)
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + chunk_delta, end)
            readings_by_spin = await self._client.async_get_electricity_half_hourly(
                self.account_number, chunk_start, chunk_end
            )
            if spin is not None:
                readings = readings_by_spin.get(spin) or []
            else:
                readings = [r for rs in readings_by_spin.values() for r in rs]
            for reading in readings:
                start_at = reading.get("startAt")
                if not start_at:
                    continue
                reading_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
                hour_start = reading_dt.replace(minute=0, second=0, microsecond=0)
                bucket = hourly.setdefault(hour_start, {"value": 0.0, "cost": 0.0})
                bucket["value"] += float(reading.get("value") or 0)
                bucket["cost"] += float(reading.get("costEstimate") or 0)
            chunk_start = chunk_end
        return hourly

    async def _async_sync_entity_level_statistics(self) -> None:
        """Backfill full history for the Total Consumption / Total Cost
        sensor entities' own long-term statistics too.

        `_async_insert_statistics_for_spin` uses `async_add_external_statistics`
        to write to a separate external statistic_id
        (`octopus_energy_jp:<account>_<spin>_xxx`), which is a completely
        different record from these two sensor entities' own long-term
        statistics (`sensor.xxx_total_consumption`) -- the latter can only
        be auto-compiled by the HA recorder from the entity's own reported
        states, and can't be backfilled directly, so a freshly created
        entity's history looks empty. Here we use `async_import_statistics`
        (which can backfill history for an existing entity statistic ID)
        to write the same history into the entity's own statistic entry.

        Both entities share the same time range, so only one request is
        made to Kraken (using the earlier of the two entities' resume
        points as the shared start), avoiding duplicate requests.
        """
        registry = er.async_get(self.hass)
        consumption_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{self.account_number}_total_consumption"
        )
        cost_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{self.account_number}_total_cost"
        )
        if consumption_entity_id is None and cost_entity_id is None:
            # Neither entity is registered yet (e.g. the integration was
            # just set up and the sensor platform hasn't loaded), skip and
            # try again on the next refresh.
            return

        end = datetime.now(timezone.utc)
        pending: list[tuple[str, str, str, str, float, datetime]] = []
        starts: list[datetime] = []

        for entity_id, name, unit, value_key in (
            (consumption_entity_id, "Octopus Energy Japan Total Consumption", "kWh", "value"),
            (cost_entity_id, "Octopus Energy Japan Total Cost", "JPY", "cost"),
        ):
            if entity_id is None:
                continue
            total_sum, start = await self._async_get_resume_point(entity_id)
            if start >= end:
                continue
            pending.append((entity_id, name, unit, value_key, total_sum, start))
            starts.append(start)

        if not pending:
            return

        fetch_start = min(starts)
        hourly = await self._async_fetch_hourly_buckets(fetch_start, end)
        if not hourly:
            return

        for entity_id, name, unit, value_key, total_sum, start in pending:
            self._import_entity_statistic(
                entity_id, name, unit, value_key, hourly, total_sum, start
            )

    def _import_entity_statistic(
        self,
        entity_id: str,
        name: str,
        unit: str,
        value_key: str,
        hourly: dict[datetime, dict[str, float]],
        total_sum: float,
        start: datetime,
    ) -> None:
        """Backfill the per-hour data (summed across all spins) into a
        sensor entity's own statistic entry (`statistic_id` is the
        entity's `entity_id`; `source` must be `"recorder"`, a hard
        requirement of `async_import_statistics`, unlike
        `async_add_external_statistics` which requires `source` to be the
        integration's own domain).
        """
        stats: list[StatisticData] = []
        for hour_start in sorted(hourly):
            if hour_start < start:
                continue
            value = hourly[hour_start][value_key]
            total_sum += value
            stats.append(StatisticData(start=hour_start, state=value, sum=total_sum))

        if not stats:
            return

        metadata: dict[str, Any] = {
            "has_sum": True,
            "name": name,
            "source": RECORDER_DOMAIN,
            "statistic_id": entity_id,
            "unit_class": None,
            "unit_of_measurement": unit,
        }
        if _MEAN_TYPE_NONE is not None:
            metadata["mean_type"] = _MEAN_TYPE_NONE
        else:
            metadata["has_mean"] = False

        _LOGGER.debug("Writing %s statistics to entity statistic %s", len(stats), entity_id)
        async_import_statistics(self.hass, metadata, stats)  # type: ignore[arg-type]

    async def _async_get_resume_point(
        self, statistic_id: str
    ) -> tuple[float, datetime]:
        """Return (existing cumulative sum, which hourly bucket to resume
        fetching from).

        If nothing has been written yet (first-time setup), start
        backfilling from STATISTICS_BACKFILL_DAYS days ago.
        """
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        if not last_stat:
            start = datetime.now(timezone.utc) - timedelta(days=STATISTICS_BACKFILL_DAYS)
            return 0.0, start

        row = last_stat[statistic_id][0]
        start = dt_util.utc_from_timestamp(row["end"])
        return float(row.get("sum") or 0.0), start

    async def _async_get_period_total(
        self, statistic_ids: set[str], start: datetime
    ) -> float:
        """Sum the hourly deltas from `start` to now (across all given
        statistic_ids, e.g. multiple meters), reading directly from HA's
        own long-term statistics table.

        Used to compute This Week's / This Month's Consumption/Cost
        without re-querying Kraken -- the data source is the hourly
        statistics already written by `_async_insert_statistics_for_spin`
        on every refresh; the `state` field is that hour's delta (not the
        cumulative `sum`), so summing it directly works, with no extra API
        cost and no risk of Kraken silently truncating a large-range query.
        """
        if not statistic_ids:
            return 0.0

        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            None,
            statistic_ids,
            "hour",
            None,
            {"state"},
        )
        total = 0.0
        for stat_rows in rows.values():
            for row in stat_rows:
                total += float(row.get("state") or 0)
        return total

