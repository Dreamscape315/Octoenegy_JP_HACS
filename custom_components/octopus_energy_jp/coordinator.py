"""DataUpdateCoordinator for Octopus Energy Japan.

除了给 sensor.py 提供"最新一条半小时读数/账户余额"这种实时展示数据外，
还会把半小时读数按小时聚合后写入 Home Assistant 的长期统计表
（homeassistant.components.recorder.statistics），这样用户可以直接在
设置 → 仪表盘 → 能源 里把本集成选为"电网消耗"来源，且首次运行会自动
回填历史数据。写法参考了 HA 核心自带的 `opower` 集成（同类"从电力公司
拉用量数据"的官方集成）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

try:
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_TYPE_NONE = StatisticMeanType.NONE
except ImportError:  # 兼容更早期不带 StatisticMeanType 的 HA 版本
    _MEAN_TYPE_NONE = None

from .api import OctopusJapanApiClient, OctopusJapanApiError
from .const import DEFAULT_SCAN_INTERVAL_MINUTES, DOMAIN, STATISTICS_BACKFILL_DAYS

_LOGGER = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("_", value.lower()).strip("_")


class OctopusJapanDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """定期拉取账户信息、写入长期统计，并提供最近几小时读数给传感器展示。"""

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

        try:
            await self._async_insert_statistics(account)
        except OctopusJapanApiError as err:
            # Energy Dashboard 统计导入失败不应该让整个 coordinator 挂掉，
            # 记录警告即可，下次刷新会自动重试。
            _LOGGER.warning("导入 Energy Dashboard 长期统计数据失败: %s", err)

        now = datetime.now(timezone.utc)
        try:
            readings_by_spin = await self._client.async_get_electricity_half_hourly(
                self.account_number, now - timedelta(hours=6), now
            )
        except OctopusJapanApiError as err:
            raise UpdateFailed(str(err)) from err

        all_readings = [r for readings in readings_by_spin.values() for r in readings]
        all_readings.sort(key=lambda r: r.get("startAt") or "")
        latest_reading = all_readings[-1] if all_readings else None

        return {
            "account": account,
            "latest_reading": latest_reading,
        }

    def _get_spins(self, account: dict[str, Any]) -> list[str]:
        spins: list[str] = []
        for prop in account.get("properties") or []:
            for sp in prop.get("electricitySupplyPoints") or []:
                spin = sp.get("spin")
                if spin and spin not in spins:
                    spins.append(spin)
        return spins

    async def _async_insert_statistics(self, account: dict[str, Any]) -> None:
        for spin in self._get_spins(account):
            await self._async_insert_statistics_for_spin(spin)

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

    async def _async_insert_statistics_for_spin(self, spin: str) -> None:
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
            return

        readings_by_spin = await self._client.async_get_electricity_half_hourly(
            self.account_number, start, end
        )
        readings = readings_by_spin.get(spin) or []
        if not readings:
            return

        hourly: dict[datetime, dict[str, float]] = {}
        for reading in readings:
            start_at = reading.get("startAt")
            if not start_at:
                continue
            reading_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            hour_start = reading_dt.replace(minute=0, second=0, microsecond=0)
            bucket = hourly.setdefault(hour_start, {"value": 0.0, "cost": 0.0})
            bucket["value"] += float(reading.get("value") or 0)
            bucket["cost"] += float(reading.get("costEstimate") or 0)

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
                "写入 %s 条 consumption 统计到 %s", len(consumption_stats), consumption_stat_id
            )
            async_add_external_statistics(self.hass, consumption_metadata, consumption_stats)
        if cost_stats:
            _LOGGER.debug("写入 %s 条 cost 统计到 %s", len(cost_stats), cost_stat_id)
            async_add_external_statistics(self.hass, cost_metadata, cost_stats)

    async def _async_get_resume_point(
        self, statistic_id: str
    ) -> tuple[float, datetime]:
        """返回 (已有的累计 sum, 应该从哪个整点小时开始继续拉数据)。

        如果之前没写过任何统计（首次设置集成），就从 STATISTICS_BACKFILL_DAYS
        天前开始回填。
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
