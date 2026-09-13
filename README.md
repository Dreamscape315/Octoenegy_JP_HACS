# Octopus Energy Japan – Home Assistant Integration

[English](#english) | [中文说明](#中文说明)

---

<a name="english"></a>
## English

An unofficial Home Assistant custom integration that brings electricity consumption and cost data from **Octopus Energy Japan** into Home Assistant.

### Features

- **Direct Web Login**: Sign in using your `octopusenergy.co.jp` account email and password via the UI config flow—no API key required.
- **Multi-Account Support**: Easily select your target account if multiple accounts are associated with your login.
- **Home Assistant Energy Dashboard Integration**:
  - Automatically aggregates half-hourly electricity usage and estimated costs into top-of-the-hour external statistics (`recorder external statistics`).
  - Seamlessly add grid consumption (`..._consumption`) and cost tracking (`..._cost`) in **Settings → Dashboards → Energy**.
  - Automatically backfills historical data on initial setup (default: 30 days).
- **Real-Time Sensor Entities**:
  - **Latest Half-Hourly Consumption** (`Latest Half-Hourly Consumption`, kWh)
  - **Latest Half-Hourly Cost Estimate** (`Latest Half-Hourly Cost Estimate`, JPY)
  - **Account Balance** (`Account Balance`, JPY)

### Installation

#### Method 1: HACS Custom Repository (Recommended)

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top-right corner → **Custom repositories**.
3. Enter Repository URL: `https://github.com/Dreamscape315/Octoenegy_JP_HACS` and set Category to **Integration**, then click **Add**.
4. Search for **Octopus Energy Japan** in HACS and download it.
5. Restart Home Assistant.

#### Method 2: Manual Installation

1. Download this repository.
2. Copy the `custom_components/octopus_energy_jp` folder into your Home Assistant `<config>/custom_components/` directory.
3. Restart Home Assistant.

### Configuration

1. In Home Assistant, go to **Settings → Devices & Services → Add Integration**.
2. Search for **Octopus Energy Japan**.
3. Enter your Octopus Energy Japan account **email and password**.
4. Set up the **Energy Dashboard**:
   - Go to **Settings → Dashboards → Energy**.
   - Under **Electricity grid**, click **Add consumption** and select `Octopus Energy Japan <SPIN> Consumption`.
   - Under **Track costs**, choose **Use an entity tracking the total costs** and select `Octopus Energy Japan <SPIN> Cost`.

### Acknowledgements

- [bottlecapdave/HomeAssistant-OctopusEnergy](https://github.com/bottlecapdave/HomeAssistant-OctopusEnergy) - Home Assistant integration for Octopus Energy UK.
- [caru-ini/octopus-bot](https://github.com/caru-ini/octopus-bot) - Reference implementation for Octopus Energy Japan Kraken GraphQL API authentication and queries.

---

<a name="中文说明"></a>
## 中文说明

这是一个非官方的 Home Assistant 自定义集成，用于将 **Octopus Energy Japan** 的用电数据与费用无缝接入 Home Assistant。

### 功能特性

- **直接使用官网账号登录**：支持在 UI 配置向导中直接输入 `octopusenergy.co.jp` 的官网邮箱与密码登录，无需申请 API Key。
- **支持多账户管理**：如果一个账号下拥有多个电力账户，配置时支持交互式选择。
- **深度适配 Energy Dashboard（能源仪表盘）**：
  - 自动将半小时用电量及预估费用按整点聚合后写入 Home Assistant 外部长期统计（`recorder external statistics`）。
  - 可直接在 **设置 → 仪表盘 → 能源** 中添加电网消耗（`..._consumption`）和跟踪成本（`..._cost`）。
  - 首次配置自动回填历史用电数据（默认回填 30 天）。
- **实时传感器实体**：
  - **最新半小时用电量**（`Latest Half-Hourly Consumption`，单位 kWh）
  - **最新半小时预估费用**（`Latest Half-Hourly Cost Estimate`，单位 JPY）
  - **账户余额**（`Account Balance`，单位 JPY）

### 安装方法

#### 方式一：通过 HACS 自定义存储库安装（推荐）

1. 打开 Home Assistant 的 **HACS** 页面。
2. 点击右上角菜单（三个点）→ **自定义存储库（Custom repositories）**。
3. 输入存储库 URL：`https://github.com/Dreamscape315/Octoenegy_JP_HACS`，类别选择 **集成（Integration）**，点击添加。
4. 在 HACS 列表中搜索 **Octopus Energy Japan** 并下载。
5. 重启 Home Assistant。

#### 方式二：手动安装

1. 下载本仓库，将 `custom_components/octopus_energy_jp` 目录拷贝到你的 Home Assistant 配置目录下的 `custom_components/` 文件夹中。
2. 重启 Home Assistant。

### 配置与使用

1. 在 Home Assistant 中进入 **设置 → 设备与服务 → 添加集成**。
2. 搜索 **Octopus Energy Japan**。
3. 输入你的 Octopus Energy Japan 官网**邮箱和密码**完成添加。
4. 进入 **设置 → 仪表盘 → 能源**：
   - 在 **电网消耗** 中点击 **添加消耗**，选择 `Octopus Energy Japan <SPIN> Consumption`；
   - 在 **追踪成本** 中选择 **使用条目跟踪成本**，选择 `Octopus Energy Japan <SPIN> Cost`。

### 鸣谢与参考

- [bottlecapdave/HomeAssistant-OctopusEnergy](https://github.com/bottlecapdave/HomeAssistant-OctopusEnergy) - 英国官方社区的 Home Assistant Octopus Energy 集成。
- [caru-ini/octopus-bot](https://github.com/caru-ini/octopus-bot) - 日本站 Kraken GraphQL API 认证机制与调用的参考实现。
