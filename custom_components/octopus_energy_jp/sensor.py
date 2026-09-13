"""Sensor platform for Octopus Energy Japan."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT_NUMBER, DOMAIN
from .coordinator import OctopusJapanDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OctopusJapanDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OctopusJapanLatestConsumptionSensor(coordinator, entry),
            OctopusJapanLatestCostEstimateSensor(coordinator, entry),
            OctopusJapanBalanceSensor(coordinator, entry),
        ]
    )


class OctopusJapanBaseSensor(CoordinatorEntity[OctopusJapanDataUpdateCoordinator], SensorEntity):
    """所有传感器共用的 DeviceInfo 逻辑。"""

    def __init__(
        self, coordinator: OctopusJapanDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._account_number = entry.data[CONF_ACCOUNT_NUMBER]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=f"Octopus Energy Japan ({self._account_number})",
            manufacturer="Octopus Energy",
            model="Kraken API",
        )


class OctopusJapanLatestConsumptionSensor(OctopusJapanBaseSensor):
    """最近一个已出结果的半小时用电量（kWh）。"""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_name = "Latest Half-Hourly Consumption"

    @property
    def unique_id(self) -> str:
        return f"{self._account_number}_latest_half_hourly_consumption"

    @property
    def native_value(self) -> float | None:
        reading = self.coordinator.data.get("latest_reading")
        if not reading:
            return None
        return float(reading["value"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self.coordinator.data.get("latest_reading")
        if not reading:
            return {}
        return {
            "start_at": reading.get("startAt"),
            "end_at": reading.get("endAt"),
        }


class OctopusJapanLatestCostEstimateSensor(OctopusJapanBaseSensor):
    """对应半小时用电量的预估费用（円）。"""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "JPY"
    _attr_name = "Latest Half-Hourly Cost Estimate"

    @property
    def unique_id(self) -> str:
        return f"{self._account_number}_latest_half_hourly_cost"

    @property
    def native_value(self) -> float | None:
        reading = self.coordinator.data.get("latest_reading")
        if not reading:
            return None
        return float(reading["costEstimate"])


class OctopusJapanBalanceSensor(OctopusJapanBaseSensor):
    """账户余额（正数=有余额/负数=欠费，具体符号含义以官方账单为准）。"""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "JPY"
    _attr_name = "Account Balance"

    @property
    def unique_id(self) -> str:
        return f"{self._account_number}_balance"

    @property
    def native_value(self) -> float | None:
        account = self.coordinator.data.get("account")
        if not account:
            return None
        return account.get("balance")
