"""
Octopus Energy Japan (Kraken) GraphQL API client.

以下所有查询字段都经过对
https://api.oejp-kraken.energy/v1/graphql/
做完整 introspection 验证过，字段名/参数/返回类型均与真实线上 schema 一致。

认证方式：
    实测确认使用「邮箱 + 密码」（跟登录 octopusenergy.co.jp 官网用的是同一套账号密码）。

    obtainKrakenToken(input: {email: "...", password: "..."}) -> token

    重要：虽然 introspection 显示 ObtainJSONWebTokenInput 只暴露
    APIKey / organizationSecretKey / preSignedKey / refreshToken 几个字段
    （Kraken 后台把 email/password 字段故意从 introspection 里隐藏了），
    但实测直接传 email/password 是被服务端接受并处理的 —— 用假账号密码测试时，
    返回的是业务错误 "Please make sure the credentials are correct."
    (errorCode KT-CT-1138)，而不是 GraphQL 层面的 "字段不存在" 校验错误，
    这证明该字段是真实存在且生效的。
    （做法参考自开源项目 caru-ini/octopus-bot，其在生产环境中已验证可用。）

    之后所有请求都带 `Authorization: JWT <token>` header
    （注意有 "JWT " 前缀，不是裸 token）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    GRAPHQL_URL,
    TOKEN_ASSUMED_LIFETIME_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


class OctopusJapanApiError(Exception):
    """通用 API 错误。"""


class OctopusJapanAuthError(OctopusJapanApiError):
    """邮箱/密码无效或 token 过期等认证类错误。"""


TOKEN_MUTATION = """
mutation krakenTokenAuthentication($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    token
    refreshToken
    refreshExpiresIn
  }
}
"""

VIEWER_ACCOUNTS_QUERY = """
query getViewerAccounts {
  viewer {
    id
    email
    accounts {
      number
      status
      balance
    }
  }
}
"""

ACCOUNT_QUERY = """
query getAccount($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    number
    balance
    properties {
      id
      address
      electricitySupplyPoints {
        id
        spin
        status
        meters {
          serialNumber
        }
      }
    }
  }
}
"""

ELECTRICITY_HALF_HOURLY_QUERY = """
query getElectricityUsage(
  $accountNumber: String!
  $fromDatetime: DateTime
  $toDatetime: DateTime
) {
  account(accountNumber: $accountNumber) {
    properties {
      electricitySupplyPoints {
        spin
        halfHourlyReadings(fromDatetime: $fromDatetime, toDatetime: $toDatetime) {
          startAt
          endAt
          value
          costEstimate
        }
      }
    }
  }
}
"""


def _dt_to_graphql(dt: datetime) -> str:
    """转成 Kraken GraphQL DateTime 标量接受的 ISO8601 字符串。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class OctopusJapanApiClient:
    """封装对 Octopus Energy Japan Kraken GraphQL API 的调用。"""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        require_auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if require_auth:
            # 注意：Kraken 要求的 Authorization header 格式是 "JWT <token>"，
            # 不是裸 token（实测确认，参考 caru-ini/octopus-bot 的实现）。
            headers["Authorization"] = f"JWT {await self._async_ensure_token()}"

        async with self._session.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            payload = await resp.json()

        if "errors" in payload and payload["errors"]:
            err = payload["errors"][0]
            ext = err.get("extensions", {}) or {}
            code = ext.get("errorCode")
            message = ext.get("errorDescription") or err.get("message") or "Unknown error"

            if code == "KT-CT-1138" or "credentials are correct" in message:
                raise OctopusJapanAuthError(f"邮箱或密码不正确：{message}")
            if code in ("KT-CT-1139", "KT-CT-1134", "KT-CT-1135") or "Authentication failed" in message:
                raise OctopusJapanAuthError(f"登录失败：{message}")
            if "Authorization" in message and "header" in message:
                raise OctopusJapanAuthError(f"缺少或无效的 Authorization header：{message}")

            raise OctopusJapanApiError(f"{code}: {message}")

        return payload.get("data") or {}

    async def _async_ensure_token(self) -> str:
        if (
            self._token is not None
            and self._token_expires_at is not None
            and datetime.now(timezone.utc) < self._token_expires_at
        ):
            return self._token
        await self._async_login()
        assert self._token is not None
        return self._token

    async def _async_login(self) -> None:
        variables = {"input": {"email": self._email, "password": self._password}}
        data = await self._graphql(TOKEN_MUTATION, variables, require_auth=False)
        result = data.get("obtainKrakenToken")
        if not result or not result.get("token"):
            raise OctopusJapanAuthError("登录失败：未能获取到有效 token。")

        self._token = result["token"]
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=TOKEN_ASSUMED_LIFETIME_MINUTES
        )

    async def async_validate(self) -> None:
        """在 config_flow 中用来校验用户填的邮箱/密码是否有效。"""
        await self._async_login()

    async def async_get_accounts(self) -> list[dict[str, Any]]:
        """获取当前登录账号下的所有账户号（一般只有一个）。"""
        data = await self._graphql(VIEWER_ACCOUNTS_QUERY)
        viewer = data.get("viewer") or {}
        return viewer.get("accounts") or []

    async def async_get_account(self, account_number: str) -> dict[str, Any]:
        """获取账户基本信息 + 名下所有物业(property)/电表(supply point)。"""
        data = await self._graphql(ACCOUNT_QUERY, {"accountNumber": account_number})
        return data.get("account") or {}

    async def async_get_electricity_half_hourly(
        self,
        account_number: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        """获取指定时间范围内每个电表(spin)各自的半小时用电量读数（kWh + 预估费用）。

        返回 {spin: [reading, ...]}，按 spin 分组是为了给 Energy Dashboard
        的长期统计（每个电表一条 statistic_id）使用；如果只是想要一个整体的
        "最新读数"展示，可以把所有 spin 的读数拼在一起再取最后一条。
        """
        data = await self._graphql(
            ELECTRICITY_HALF_HOURLY_QUERY,
            {
                "accountNumber": account_number,
                "fromDatetime": _dt_to_graphql(from_dt),
                "toDatetime": _dt_to_graphql(to_dt),
            },
        )
        account = data.get("account") or {}
        readings_by_spin: dict[str, list[dict[str, Any]]] = {}
        for prop in account.get("properties") or []:
            for supply_point in prop.get("electricitySupplyPoints") or []:
                spin = supply_point.get("spin")
                if not spin:
                    continue
                readings = supply_point.get("halfHourlyReadings") or []
                bucket = readings_by_spin.setdefault(spin, [])
                bucket.extend(readings)

        for readings in readings_by_spin.values():
            readings.sort(key=lambda r: r.get("startAt") or "")

        return readings_by_spin
