# scripts/

这里只保留两个还有长期使用价值的脚本，其余在探测 GraphQL schema 过程中
用过的一次性调试脚本都已经删掉（内容已经沉淀进根目录 `README.md` 的
"已验证的关键事实"一节，不需要再保留代码）。

- **`dump_schema.py`** — 对 Octopus Energy Japan 的 GraphQL 端点做一次完整
  introspection，把 schema 存成本地 json。如果以后怀疑 Kraken 那边改了字段，
  重新跑一下这个脚本对比即可。
- **`test_login.py`** — 用真实邮箱/密码跑一遍
  `custom_components/octopus_energy_jp/api.py` 里的核心逻辑（登录、查账户、
  查半小时用电量），不需要安装完整的 Home Assistant 就能验证 API 调用链路
  是否正常。

两个脚本都只依赖 `aiohttp`（可通过 `pip install aiohttp` 安装）。

