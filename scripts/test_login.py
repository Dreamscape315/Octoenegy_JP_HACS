"""
Test OctopusJapanApiClient directly with credentials.

Usage:
    export OCTOPUS_EMAIL="your_email"
    export OCTOPUS_PASSWORD="your_password"
    python3 scripts/test_login.py

Optionally specify an account number:
    python3 scripts/test_login.py --account A-XXXXXXX
"""
import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

# Allow importing custom_components package without Home Assistant
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp  # noqa: E402

from custom_components.octopus_energy_jp.api import (  # noqa: E402
    OctopusJapanApiClient,
    OctopusJapanApiError,
    OctopusJapanAuthError,
)


def _mask(value: str) -> str:
    if not value:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test Octopus Energy Japan API client")
    parser.add_argument("--account", help="Account number (defaults to first account)")
    parser.add_argument(
        "--days", type=int, default=3, help="Number of days of half-hourly usage to query (default: 3)"
    )
    args = parser.parse_args()

    email = os.environ.get("OCTOPUS_EMAIL") or input("Octopus Email: ").strip()
    password = os.environ.get("OCTOPUS_PASSWORD") or getpass.getpass("Octopus Password: ")

    print(f"\nUsing email: {email}")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        client = OctopusJapanApiClient(session, email, password)

        # 1. Authentication
        print("\n[1/4] Authenticating (obtainKrakenToken)...")
        try:
            await client.async_validate()
        except OctopusJapanAuthError as err:
            print(f"❌ Authentication failed: {err}")
            return
        except OctopusJapanApiError as err:
            print(f"❌ API error: {err}")
            return
        print("✅ Authentication successful, token acquired.")

        # 2. Account list
        print("\n[2/4] Fetching accounts (viewer.accounts)...")
        try:
            accounts = await client.async_get_accounts()
        except OctopusJapanApiError as err:
            print(f"❌ Failed to fetch accounts: {err}")
            return

        if not accounts:
            print("⚠️ No accounts found for this login.")
            return

        print(f"✅ Found {len(accounts)} account(s):")
        for acc in accounts:
            print(f"   - number={acc.get('number')} status={acc.get('status')} balance={acc.get('balance')}")

        account_number = args.account or accounts[0]["number"]
        print(f"\nUsing account number: {account_number}")

        # 3. Account details
        print("\n[3/4] Fetching account details (account -> properties -> electricitySupplyPoints)...")
        try:
            account = await client.async_get_account(account_number)
        except OctopusJapanApiError as err:
            print(f"❌ Failed to fetch account details: {err}")
            return

        print(f"✅ Account number: {account.get('number')}, Balance: {account.get('balance')}")
        properties = account.get("properties") or []
        print(f"   Found {len(properties)} property/properties:")
        all_spins = []
        for prop in properties:
            print(f"   - property id={prop.get('id')} address={prop.get('address')!r}")
            sps = prop.get("electricitySupplyPoints") or []
            for sp in sps:
                spin = sp.get("spin")
                all_spins.append(spin)
                meters = sp.get("meters") or []
                serials = [m.get("serialNumber") for m in meters]
                print(
                    f"       electricitySupplyPoint spin={spin} status={sp.get('status')} "
                    f"meters={serials}"
                )

        if not all_spins:
            print("⚠️ No electricitySupplyPoint (spin) found for this account.")
            return

        # 4. Half-hourly usage
        print(f"\n[4/4] Fetching past {args.days} days of half-hourly usage (halfHourlyReadings)...")
        now = datetime.now(timezone.utc)
        try:
            readings_by_spin = await client.async_get_electricity_half_hourly(
                account_number, now - timedelta(days=args.days), now
            )
        except OctopusJapanApiError as err:
            print(f"❌ Failed to fetch electricity usage: {err}")
            return

        if not readings_by_spin:
            print("⚠️ No half-hourly readings returned for the specified period.")
        for spin, readings in readings_by_spin.items():
            print(f"\n   spin={spin}: {len(readings)} readings found")
            if readings:
                first, last = readings[0], readings[-1]
                total_kwh = sum(float(r["value"]) for r in readings)
                total_cost = sum(float(r.get("costEstimate") or 0) for r in readings)
                print(f"     Earliest: {first['startAt']} ~ {first['endAt']}  value={first['value']} kWh")
                print(f"     Latest:   {last['startAt']} ~ {last['endAt']}  value={last['value']} kWh")
                print(f"     Period Total: {total_kwh:.3f} kWh, Estimated Cost: {total_cost:.1f} JPY")

    print("\n" + "=" * 60)
    print("✅ All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
