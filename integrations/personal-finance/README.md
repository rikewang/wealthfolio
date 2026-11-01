# 本地个人资产管理 · Wealthfolio

本目录提供独立的 AKShare 行情服务、可选 Docker
Compose 部署及本地管理脚本。下文“已验证”描述 2026-11-01 的本机验收记录；新克隆不包含登录口令、加密密钥、数据库、行情缓存或验收报告，AI 网关也需自行配置。

已安装官方 **Wealthfolio 3.11.0**，使用 Docker
Compose；独立 Python 行情服务已接入 **AKShare
1.20.2**，获取中国市场公开数据。2026-11-01 已通过本机 **Magpie 0.1.2430**
接入现有 Codex / ChatGPT 登录，供 Wealthfolio
AI 助手使用。没有修改 Wealthfolio 源码，没有券商登录或自动交易。

产品规划：[需求差距、功能精简与演进计划](docs/requirements-and-roadmap.md)，记录当前能力、缺口、建议优先级及阶段验收标准。

近期收口：[功能与代码收口计划](docs/feature-consolidation-plan.md)，按“先隐藏、验证、停用，再按依赖删除”推进，保留现有账本和演示数据。

代码仓库：[个人 Fork：rikewang/wealthfolio](https://github.com/rikewang/wealthfolio)，上游为
[wealthfolio/wealthfolio](https://github.com/wealthfolio/wealthfolio)。本目录纳入部署代码、AKShare 适配器和产品规划；运行数据在使用者本机生成。Compose 使用固定的官方 3.11.0 镜像，与仓库根目录的源码开发流程独立。

架构影响（Architecture impact）：复用 Wealthfolio 官方自定义数据源与 REST
API，Python 服务只请求公开行情并保存行情缓存。AKShare 的同步请求及基金 JavaScript 解析可能阻塞，已有异步 HTTP 超时不能终止这些调用，因此沿用已验证的限时子进程。账户和交易仍由 Wealthfolio 管理；本次移入仓库不改动 Rust、React、数据库结构或券商同步机制。

## 打开使用

- 页面：**http://localhost:8088**
- 登录口令：本项目
  `.secrets/local-login-password.txt`，在本机文件编辑器查看即可。口令不会写入本文或终端日志。
- 行情诊断：http://localhost:8090/status ，接口说明：http://localhost:8090/docs
- 左下角档案菜单可切换 **个人资产** 和
  **数据接入验证（示例）**。前者没有真实或示例持仓；后者的数量、成本全部是验证用样本。

使用“个人资产”时，在账户管理中建立一个人民币账户，选择“持仓 /
Holdings”跟踪模式，给它取一个标签，例如“证券资产”或“基金资产”；不用填写真实账号、密码或券商连接。之后录入证券、份额/股数、平均成本和现金余额。

预先登记的证券有
`600519.SS`、`110022.OF`、`518880.SS`、`AU9999.SGE`；可以通过名称或代码查找。黄金现货样本的数量单位是
**克**，黄金 ETF 是
**份**。现货行情只是实物金估值参考，不含金饰工费、回购价差和成色折价。

Wealthfolio
3.11.0 原版部分卡片和详情使用通用的“股/股份”文案：现货黄金即使显示“10 股”，此接入配置仍代表
**10 克**，按 10
× 元/克估值；以名称中的“按克”和资产备注为准。持仓列表中的公募基金与 ETF 已分别配置为 Mutual
Fund / ETF，数量显示“份”；首页卡片和部分详情仍可能沿用通用文案。

初始页面的个人资产是空的，若想先看效果，请切换到“数据接入验证（示例）”。该档案已扩充为完整的模拟家庭财务场景；原四个接口核验样本仍保留，已转换为等值交易流水。

## 完整演示场景

2026-11-01 已补充，全部写入独立示例档案：

- **9 个账户、16 个投资标的**：A 股、宽基与行业 ETF、两只场外基金、国债 ETF、黄金 ETF、按克计价的黄金、港股、美股和比特币；覆盖人民币、港币、美元。
- **464 条模拟流水**：从 2025-01 到 2026-11 的入金、买卖、定投、现金分红、工资、奖金、利息、消费、还贷现金支出以及 44 对内部转账。
- **资产负债**：一套自住房、一辆汽车和两笔关联贷款，22 个月的手工估值。还贷流水展示含本金和利息的现金支出，余额另按模拟月度估值记录。
- **规划与分析**：3 个投资组合、2 套配置目标、6 个新增资金目标、10 类消费预算、2 次旅行事件；保留已有退休规划。
- 股票、基金、黄金和海外标的使用实际抓取的公开历史行情；**份额、成本对应的交易、分红金额、所有现金流、房产/车辆估值及目标假设均为虚构演示**。这些收益和配置建议不能代表真实策略回测或实际账户表现。

推荐浏览路径：

1. [洞察概览](http://localhost:8088/insights)：资产配置、货币、涨跌排行、目标偏离；可切换“全景投资组合（模拟）”。
2. [净资产](http://localhost:8088/dashboard?tab=net-worth)：家庭总资产、负债和历史曲线。
3. [收益表现](http://localhost:8088/insights?tab=performance)
   与收入页：收益率、回撤、分红和利息。
4. [上月支出](http://localhost:8088/dashboard?tab=spending&spendingInterval=LAST_MONTH)：工资、消费、预算和旅行事件。当前为月初，上月内容更完整。
5. [目标](http://localhost:8088/goals)：应急金、教育、旅行、换车、住房改善和长期投资的情景测算。

`./finance demo`
可补齐本场景；按来源记录标识去重，不重复生成交易，会重新应用演示的分类、备注、目标和估值假设。`scripts/enrich_demo.py`
只允许写入标注为“示例”的指定档案。

`.venv/bin/python scripts/check_demo.py`
只读核对模拟流水、份额、现金余额、内部转账、收支分类、净资产恒等式及个人档案未变化；结果保存到
`data/demo-rich-verification.json`。

## 已实测数据

以下为 2026-10-30 的公开报价，不是实时价格，也不是投资推荐。

| 类型     | 样本                           |          报价 | 已写入 Wealthfolio 的历史     | 数据来源               |
| -------- | ------------------------------ | ------------: | ----------------------------- | ---------------------- |
| A 股     | 贵州茅台 `600519.SS`           | 1392.05 元/股 | 640 个交易日，始于 2024-03-11 | 腾讯财经未复权日线     |
| 场外基金 | 易方达消费行业股票 `110022.OF` |   2.871 元/份 | 1215 点，始于 2021-11-01      | 天天基金正式单位净值   |
| 黄金 ETF | 华安黄金 ETF `518880.SS`       |   8.115 元/份 | 640 个交易日，始于 2024-03-11 | 腾讯财经未复权日线     |
| 现货黄金 | 上金所 `AU9999.SGE`            |  854.76 元/克 | 1213 点，始于 2021-11-01      | 上海黄金交易所 Au99.99 |

`./finance check`
会再次核对：登录保护、行情价格与日期、全部已保存历史收盘价、份额乘价格的估值、数据库加密头。结果写入
`data/verification.json`，实际最新日期以接口为准。

2026-11-01 已经本机浏览器实测登录、档案切换、个人资产空状态、四类样本持仓、基金和黄金的 5 年曲线及价格历史表。示例组合总值为 ¥151,435.10；基金列表已显示“份”。未配置的 Connect 会记录会话恢复失败，部分证券 Logo 缺失时显示代码缩写，均不影响本地持仓读取。

国内样本均指定走本地适配器；Yahoo
Finance 则保留用于其支持的海外证券和汇率。**市场行情刷新与 Wealthfolio
Connect 的跨设备/券商同步是不同功能**，Yahoo 不需要开通 Connect 或提供 API
Key。首次配置曾关闭 Yahoo，造成 `USD/CNY`
无数据源，已于 2026-11-01 恢复，并实测保存 24 条 Yahoo 汇率记录、清除同步告警，Connect 仍关闭；之后网络与同步是否成功仍应查看报价日期。原版部分数量单位及 OHLC 占位显示限制见本页说明。

## 日常命令

在此目录执行，需 OrbStack/Docker 正在运行：

```bash
./finance start       # 启动/重建，保留现有数据
./finance status      # 容器健康与端口
./finance demo        # 补齐完整模拟场景；会重新应用演示假设
./finance refresh     # 请求增量更新所有未锁定档案已登记证券的行情
./finance check       # 只读检查独立验证档案；初次同步未完成时可稍后重试
./finance test        # 运行 12 项离线数据语义与失败处理测试
./finance backup     # 暂停 Wealthfolio 写入、备份、重新启动
./finance stop       # 停服务，保留数据
```

页面中也可手动刷新行情。数据源缓存 15 分钟；刷新并不代表上游已公布新净值。当前没有配置无人值守的每日任务，也没有消息推送。

新增自己的观察标的：

```bash
./finance add 000001.SZ 平安银行 --type stock
./finance add 110022.OF 易方达消费行业股票 --type fund
./finance add 518880.SS 华安黄金ETF --type etf
./finance add AU9999.SGE '上金所 Au99.99（按克）' --type gold
```

命令先实测数据可用，再在“个人资产”档案登记证券和行情映射，**不会创建持仓**。随后从页面选择它、填入你的数量和成本。`.SS`
为上海、`.SZ` 为深圳、`.OF`
为场外基金。非样本代码按同类接口尝试，是否有数据以实际返回为准。该新增命令只使用国内适配器；完整演示里的港美股、比特币和对应汇率由 Wealthfolio 内置 Yahoo 数据源提供。

基金、ETF 的“产品类型”和“底层风险敞口”是不同分类；新增后请核对股票、债券、商品等敞口。已将本次黄金 ETF 样本归入商品，场外基金样本标为基金。

## 数据口径与限制

- **日频**：沪深证券用未复权日线，在上海时间 16:30 前剔除当天尚未确认的日线。不是逐笔行情、盘口或实盘交易信号。
- **基金**：读取正式单位净值，不使用盘中估值或累计净值冒充单位价格；净值公布可能滞后。没有验证所有基金类型，货币基金收益、QDII 的特殊估值日和分红再投资需另行处理。
- **收益**：当前未自动导入分红、拆股或申赎现金流。长期总收益需要完整交易/现金流记录；未复权价格曲线不能直接当成含分红总回报。
- **历史**：AKShare 分年查询腾讯未复权行情，适配器保留最近 640 根已完成日线；基金与黄金取上游实际提供的数据，首次向 Wealthfolio 写入最近 5 年。不填补不存在的历史点。
- **故障**：非法价格/日期、上游超时会明确报错；超过 10 个自然日的最新报价不作为新报价返回。这个阈值是保守检查，不是完整交易日历。停牌或长假可能需人工核对。
- Wealthfolio 在数据源失败时仍可能显示此前保存的价格，务必看报价日期；不应把“页面还能打开”理解为数据刚刚更新。
- 免费公开网页接口没有稳定性 SLA，可能限流或改格式。这版适合个人观察；更严肃的策略回测需要授权数据、复权与分红处理、交易日历和质量校验。
- Wealthfolio 映射目前只使用收盘价；适配器保留证券和黄金的 OHLC。AKShare
  1.20.2 的部分深市代码成交量单位处理不一致，本版不输出成交量，避免重复乘以 100。不把 Wealthfolio 默认填充的 OHLC/0 成交量用于 K 线量价策略。

## Codex / Magpie AI 助手

打开 [AI 助手](http://localhost:8088/assistant)。个人资产和示例档案均已配置
**OpenAI** 提供商，默认模型为 `codex/gpt-6-astra`，另收藏了 `codex/gpt-6.1-sol`
和 `codex/gpt-6-luna`。已显式登记这三个带前缀模型的工具、思考、图片和流式能力。

调用路径：Wealthfolio 容器 → `http://host.docker.internal:3425/v1` → 本机 Magpie
→ OpenAI。Magpie 直接发现并使用 `~/.codex/auth.json`
中的 ChatGPT 登录态；没有导入或迁移账户，也没有修改 Codex 的
`config.toml`。这让 Wealthfolio 使用该账户的模型服务；Wealthfolio 聊天记录仍由 Wealthfolio 自己管理。

- 应用：`/Applications/magpie.app`；命令：`~/.local/bin/magpie`。
- 网关只监听 `127.0.0.1:3425`。本机 OrbStack 已实测能通过 `host.docker.internal`
  访问，无需开启局域网共享。
- 已安装官方 LaunchAgent 后台服务，登录后启动并在异常退出后重启。关闭 Magpie 窗口不影响此服务。
- Wealthfolio 使用单独的 Magpie 网关 Key，已保存到两个档案的官方密钥仓库；本机备份在
  `.secrets/magpie-api-key.txt`。该 Key 不是 OpenAI API
  Key；Magpie 的回环接口按其设计允许本机客户端访问，不能把这个 Key 当成本机进程间的安全隔离。
- AI 问题、附件以及助手调用工具所读取的相关资产信息会发送给 OpenAI，并使用当前 ChatGPT
  / Codex 账户的额度。账户退出登录、额度不足或网络代理不可用时，AI 会受影响。
- 后台服务继承安装时的代理设置；更换代理后可重新执行 `magpie daemon install`
  更新服务环境。模型列表可读不代表推理一定可用，以聊天实际完成为准。

2026-11-01 已完成端到端验证：Magpie 返回测试文本；Wealthfolio 流式聊天成功执行只读
`get_accounts`
工具，回复“连接成功，共 9 个示例账户”，并收到完成事件。测试会话“示例账户连接验证”保留在示例档案；记录在
`data/magpie-chat-verification.json`。配置前的 AI 设置保存在
`data/ai-before-magpie-20261101-011338.json`。

```bash
~/.local/bin/magpie daemon status   # 检查网关和后台服务
~/.local/bin/magpie daemon restart  # 更新或异常后重启
~/.local/bin/magpie daemon stop     # 暂停 AI 网关
~/.local/bin/magpie daemon start    # 恢复 AI 网关
```

停用时，在两个档案各自的
[AI 提供商设置](http://localhost:8088/settings/ai-providers)
中关闭 OpenAI；若也不再使用 Magpie，可运行 `magpie daemon uninstall`
移除后台服务。不要直接删除 Codex 登录文件。

参考：[Magpie 官方说明](https://github.com/yetone/magpie)、[登录态与通用客户端接入说明](https://github.com/yetone/magpie/blob/main/docs/reference.md#signed-in-agents-as-providers)。

## AKShare 接入

市场数据设置中，自定义数据源显示为 **中国市场 · AKShare 日频**，沿用原来的
`cn-local` 标识和证券映射，无需 Connect。实际调用：

| 类型           | AKShare 函数                                       | 计价口径                                     |
| -------------- | -------------------------------------------------- | -------------------------------------------- |
| A 股、场内 ETF | `stock_zh_a_hist_tx(adjust="")`                    | 未复权日收盘价；拒绝接口返回复权序列作为替代 |
| 场外公募基金   | `fund_open_fund_info_em(indicator="单位净值走势")` | 正式单位净值，元/份                          |
| 上金所黄金     | `spot_hist_sge(symbol="Au99.99")`                  | 收盘价，元/克                                |

`/health`、`/status` 及报价 JSON 包含 `engine`、`engine_version`；报价还包含
`source_function`、真实上游和报价日期。缓存为 15 分钟，切换引擎或版本后不会复用原缓存冒充新来源。上游失败时返回错误，Wealthfolio 保留原报价及日期。

AKShare 每次在独立子进程中执行，同时最多两个；排队上限 10 秒，执行上限 40 秒，超时终止进程。行情容器内存上限为 768
MiB，只挂载公开行情缓存。基金接口会使用 AKShare 的嵌入式 JavaScript 引擎解析基金网站脚本；这与旧版只提取 JSON 的实现不同。子进程没有 Wealthfolio 密钥、数据库或持仓数据，HTTP 请求只允许已验证的四个上游域名，并限制响应大小。Wealthfolio 的自定义数据源本身有 15 秒请求超时；上游变慢时可能需要稍后重试。

切换前已生成完整本地备份，并保存 `data/akshare-ledger-before.json`
和公开行情基线
`data/akshare-baseline/`。本次切换只更新行情服务和数据源名称，不重新生成演示数据。只读复验命令：

```bash
.venv/bin/python scripts/check_akshare.py  # 与本次切换前的账本和历史价格比较
./finance check                         # 原有四类样本的端到端估值核对
.venv/bin/python scripts/check_demo.py   # 完整演示账务核对
```

`check_akshare.py`
的账本指纹是本次迁移快照；之后主动编辑账户、流水、目标等会使该比较失败，这是预期行为。验证结果保存在
`data/akshare-verification.json`。

该迁移检查需要原部署中保留的 `data/akshare-ledger-before.json` 与
`data/akshare-baseline/`，它们不随仓库发布。全新安装使用
`./finance test`，初始化样本并等待行情同步后再使用
`./finance check`；完整场景的检查仅在主动运行 `./finance demo` 后执行。

2026-11-01 本机验收通过：12 个国内标的在 AKShare 和 Wealthfolio 中价格及日期一致；与旧行情逐项比较 14,847 个历史收盘价，全部一致。刷新前后两个档案账本指纹不变，示例的 9 个账户、464 条流水、目标与非标资产保留。12 项单元测试、原有样本估值检查和完整演示账务检查通过，数据健康检查为 0 项问题。浏览器已确认“自定义提供商”中 AKShare 启用并关联 12 项资产。

需要手动回退行情实现时，把 `compose.yml` 中 `MARKET_DATA_ENGINE` 改成
`direct`，执行
`docker compose up -d --no-deps market-data`；同时将界面数据源名称改回“本地日频”。回退不会自动发生，也不会重建账本。

## 隐私、文件和备份

- 两个服务都只绑定 `127.0.0.1`，端口为 8088 / 8090；不对局域网开放。
- 开启 Wealthfolio 登录保护；两个档案数据库已启用官方加密，服务配置要求加密数据库。新增档案也遵循此设置。
- `.env` 保存服务加密密钥与登录密码哈希，`.secrets/`
  保存本机登录口令，权限限本机用户。这些文件和 `data/` 均被 `.gitignore` 排除。
- **数据库加密不能防止已取得 `.env`
  与整机访问权的人解密**。备份包含恢复所需密钥，应放在受保护的本地/加密介质；不要上传到公共仓库或分享。
- `data/wealthfolio/` 保存加密数据库、档案注册信息和应用密钥仓库；`data/market/`
  仅保存公开行情缓存。
- 没有配置券商连接、云同步或交易密钥。AI 助手通过本机 Magpie 使用 OpenAI，数据发送范围见上节。行情启用本地适配器与 Yahoo，其余内置行情提供商保持关闭；行情查询会向相应服务发送标的代码，不会发送持仓数量或成本。
- 不要删除 `.env`
  后重新生成密钥，否则已有加密数据可能无法恢复。`./finance start`
  不覆盖已有密钥。

备份落在 `backups/person-finance-时间.tar.gz`，文件权限为 600。恢复时：先
`./finance stop`，保留当前目录的备份，将选定压缩包解压到一个**新的恢复目录**，拷贝本项目代码后再启动；不要直接覆盖运行中的数据库。不能同时运行两个使用相同端口的实例。恢复包内
`.env`、`data/wealthfolio/` 与档案注册文件必须成套保存。

## 从零重建与扩展

依赖：Docker Compose（本机使用 OrbStack）、`uv`、Python
3.12。镜像已固定到 digest；Python 容器依赖也已锁定版本。

以下命令从本目录 `integrations/personal-finance/` 执行。`./finance start`
使用固定的 Compose 项目名和本机 8088 /
8090 端口；已有部署应继续在其原目录维护，勿在两个目录同时执行启动命令，以免替换原项目容器的挂载目录。

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
./finance start
# 等到 ./finance status 显示 healthy 后，仅首次执行：
./finance init-demo
./finance check
```

`init-demo`
检测到初始化记录便退出，不会重写你的持仓。初次生成的样本与个人档案相互隔离。

此目录只发布源码、文档和可生成虚构数据的脚本；`.env*`、`.secrets/`、`data/`、`backups/`、虚拟环境、缓存及数据库文件均由本目录
`.gitignore` 排除。凭据由 `scripts/setup.py`
在本机生成，不提供共享默认口令。不要使用 `git add -f` 强制加入这些文件。

代码边界：`compose.yml` 负责部署，`market_data/app.py`
负责行情接口、校验与缓存，`market_data/akshare_worker.py`
负责 AKShare 调用及字段映射，`scripts/bootstrap.py`
负责初次配置官方自定义数据源，`scripts/manage.py`
提供维护与新增标的命令。后续宏观指标、基金分类、规则提醒和博主研究应接在独立服务中；自动交易需要另行设计与明确授权。

上游参考：[Wealthfolio 官方仓库](https://github.com/afadil/wealthfolio)、[自托管文档](https://wealthfolio.app/docs/guide/self-hosting/docker-compose/)、[AKShare](https://github.com/akfamily/akshare)、[AKShare 基金源码](https://github.com/akfamily/akshare/blob/main/akshare/fund/fund_em.py)、[AKShare 上金所源码](https://github.com/akfamily/akshare/blob/main/akshare/spot/spot_sge.py)。当前容器实际安装并调用 AKShare，旧直接 HTTP 实现仅用于显式回退。
