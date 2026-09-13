"""
用真实账号密码，直接跑一遍 custom_components/octopus_energy_jp/api.py 里的
OctopusJapanApiClient —— 这是跟集成里完全一样的代码，不是另外写的测试代码，
所以这里测通了，装进 Home Assistant 里大概率也是通的。

用法（推荐用环境变量，不要把密码打在命令行历史里）：

    export OCTOPUS_EMAIL="你的邮箱"
    export OCTOPUS_PASSWORD="你的密码"
    python3 scripts/test_login.py

如果不设置环境变量，脚本会用 getpass 交互式安全输入（不回显）。

可选：如果你已经知道账户号，可以传进去跳过"自动选择第一个账户"这一步：
    python3 scripts/test_login.py --account A-XXXXXXX
"""
import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

# 让脚本可以直接 import 到 custom_components 包，不需要真的装 Home Assistant
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", help="指定账户号，跳过自动选择第一个账户")
    parser.add_argument(
        "--days", type=int, default=3, help="拉取最近多少天的半小时用电量数据（默认3天）"
    )
    args = parser.parse_args()

    email = os.environ.get("OCTOPUS_EMAIL") or input("Octopus 邮箱: ").strip()
    password = os.environ.get("OCTOPUS_PASSWORD") or getpass.getpass("Octopus 密码: ")

    print(f"\n使用邮箱: {email}")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        client = OctopusJapanApiClient(session, email, password)

        # 1. 登录
        print("\n[1/4] 登录中 (obtainKrakenToken)...")
        try:
            await client.async_validate()
        except OctopusJapanAuthError as err:
            print(f"❌ 登录失败: {err}")
            return
        except OctopusJapanApiError as err:
            print(f"❌ API 错误: {err}")
            return
        print("✅ 登录成功，拿到 token 了")

        # 2. 获取账户号列表
        print("\n[2/4] 获取账户列表 (viewer.accounts)...")
        try:
            accounts = await client.async_get_accounts()
        except OctopusJapanApiError as err:
            print(f"❌ 获取账户失败: {err}")
            return

        if not accounts:
            print("⚠️ 该账号下没有找到任何账户，后续步骤无法继续。")
            return

        print(f"✅ 找到 {len(accounts)} 个账户:")
        for acc in accounts:
            print(f"   - number={acc.get('number')} status={acc.get('status')} balance={acc.get('balance')}")

        account_number = args.account or accounts[0]["number"]
        print(f"\n将使用账户号: {account_number}")

        # 3. 获取账户详情（物业/电表）
        print("\n[3/4] 获取账户详情 (account -> properties -> electricitySupplyPoints)...")
        try:
            account = await client.async_get_account(account_number)
        except OctopusJapanApiError as err:
            print(f"❌ 获取账户详情失败: {err}")
            return

        print(f"✅ 账户号: {account.get('number')}, 余额(balance): {account.get('balance')}")
        properties = account.get("properties") or []
        print(f"   共 {len(properties)} 个 property:")
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
            print("⚠️ 没有找到任何 electricitySupplyPoint (spin)，可能这个账户没有电力合约，"
                  "或者字段结构跟我们假设的不一样。")
            return

        # 4. 获取最近几天的半小时用电量
        print(f"\n[4/4] 获取最近 {args.days} 天的半小时用电量 (halfHourlyReadings)...")
        now = datetime.now(timezone.utc)
        try:
            readings_by_spin = await client.async_get_electricity_half_hourly(
                account_number, now - timedelta(days=args.days), now
            )
        except OctopusJapanApiError as err:
            print(f"❌ 获取用电量失败: {err}")
            return

        if not readings_by_spin:
            print(
                "⚠️ 没有拿到任何半小时读数。可能原因：\n"
                "   - 这个账户/电表没有开通智能电表半小时级数据（日本智能电表覆盖率跟英国不一样）\n"
                "   - 时间范围内确实没有数据（比如刚开户没多久）\n"
                "   如果是这种情况，需要改用 intervalReadings（按结算周期/月）作为数据源。"
            )
        for spin, readings in readings_by_spin.items():
            print(f"\n   spin={spin}: 共 {len(readings)} 条读数")
            if readings:
                first, last = readings[0], readings[-1]
                total_kwh = sum(float(r["value"]) for r in readings)
                total_cost = sum(float(r.get("costEstimate") or 0) for r in readings)
                print(f"     最早: {first['startAt']} ~ {first['endAt']}  value={first['value']} kWh")
                print(f"     最新: {last['startAt']} ~ {last['endAt']}  value={last['value']} kWh")
                print(f"     区间总用电量: {total_kwh:.3f} kWh, 预估总费用: {total_cost:.1f} 円")

    print("\n" + "=" * 60)
    print("✅ 全部测试完成！如果上面每一步都是 ✅，说明这套 GraphQL 查询在你的真实账号上是可用的，")
    print("   可以放心把 custom_components/octopus_energy_jp 装进 Home Assistant 里用了。")


if __name__ == "__main__":
    asyncio.run(main())

