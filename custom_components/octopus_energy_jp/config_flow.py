"""Config flow for Octopus Energy Japan."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OctopusJapanApiClient, OctopusJapanApiError, OctopusJapanAuthError
from .const import CONF_ACCOUNT_NUMBER, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OctopusEnergyJapanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handles the config flow for Octopus Energy Japan."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._accounts: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = OctopusJapanApiClient(
                session, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            try:
                await client.async_validate()
                self._accounts = await client.async_get_accounts()
            except OctopusJapanAuthError:
                errors["base"] = "invalid_auth"
            except OctopusJapanApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while validating Octopus Energy Japan credentials")
                errors["base"] = "unknown"
            else:
                if not self._accounts:
                    errors["base"] = "no_accounts"
                else:
                    self._email = user_input[CONF_EMAIL]
                    self._password = user_input[CONF_PASSWORD]
                    if len(self._accounts) == 1:
                        return await self._async_create_entry(
                            self._accounts[0]["number"]
                        )
                    return await self.async_step_account()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick which account to set up when the login has
        access to multiple accounts."""
        if user_input is not None:
            return await self._async_create_entry(user_input[CONF_ACCOUNT_NUMBER])

        options = {acc["number"]: acc["number"] for acc in self._accounts}
        schema = vol.Schema({vol.Required(CONF_ACCOUNT_NUMBER): vol.In(options)})
        return self.async_show_form(step_id="account", data_schema=schema)

    async def _async_create_entry(self, account_number: str) -> FlowResult:
        await self.async_set_unique_id(account_number)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Octopus Energy Japan ({account_number})",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_ACCOUNT_NUMBER: account_number,
            },
        )

