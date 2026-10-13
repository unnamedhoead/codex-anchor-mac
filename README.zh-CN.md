# codex-anchor-mac

[![English](https://img.shields.io/badge/English-lightgrey?style=for-the-badge)](README.md)
[![简体中文](https://img.shields.io/badge/简体中文-blue?style=for-the-badge)](README.zh-CN.md)

把 ChatGPT 订阅的 5 小时额度窗口锚定在你指定的时刻，让窗口边界落在**工作时段之内**，
而不是之后。

> **它不增加额度，也不绕过任何限制。** 它只发一次刻意极小的请求，让滚动窗口在一个
> 对你有利的时刻*开始*。每个窗口里能用的量和其他人完全一样。

**面向 ChatGPT Plus 用户，仅限 macOS。** 两条都是刻意的限制：

- **Plus，不是 Pro。** Plus 在 2026-08-25 恢复了 5 小时窗口；
  [OpenAI 官方 pricing 文档](https://developers.openai.com/codex/pricing)写明
  Pro 目前完全没有 5 小时限额。Pro 用户没有窗口可锚定，真正卡人的是周限额，
  所以这个工具对你没用。
- **macOS，不跨平台。**

---

## 要解决的问题

Codex、Work、工作空间智能体和 ChatGPT for Excel 共享一个额度池，按滚动的 5 小时窗口
重置。窗口从你的**第一条**请求开始计时，不是整点对齐。

所以如果你 08:00 坐下，两小时烧完一个窗口的额度：

```
08:00  第一条消息   ->  窗口 08:00-13:00
10:00  额度耗尽
10:00-13:00  干等三小时
```

在你起床前发一次 anchor，会把边界整体前移，于是**更多边界落进你的工作时段**：

```
05:00  anchor（几秒钟，额度消耗可忽略）  ->  窗口 05:00-10:00
08:00  你开工，拿到一整块没动过的额度
10:00  额度耗尽 —— 而窗口恰好在同一刻翻篇
10:00  新窗口 10:00-15:00，无需等待
```

## 怎么选时间

```
anchor 时刻 = 起床时间 + 一个窗口能撑多久 − 5h
```

8:00 起床、2 小时烧完？`08:00 + 2h − 5h = 05:00`。
7:30 起床、消耗速度不变？`04:30`。

**设得太早比不设还糟**：第一个窗口在你用上多少之前就过期了，睡觉期间那部分白白浪费。

## 为什么偏偏是 macOS

同类工具多数就是一行 cron。在 macOS 上它会悄无声息地失效，而且有两种失效方式，
**都不报错**——只是任务静静地错过时间。

**1. TCC 挡住 launchd 访问受保护目录。** 把脚本放在 `~/Documents`、`~/Desktop` 或
`~/Downloads`，launchd 会以 `Operation not permitted`（exit 126）失败。安装时看起来
一切正常，因为你的终端有权限而 launchd 没有。`install.sh` 会拒绝从这些目录安装。

**2. 定时唤醒进的是 DarkWake。** `pmset` 能唤醒睡眠中的 Mac，但唤醒进的是 DarkWake，
系统会无视 idle 断言、执行 "Sleep Service Back to Sleep"，把请求冻在半途。在一台机器上
实测十晚：

| 供电 | 晚数 | 设定触发 | 请求实际发出 |
|---|---|---|---|
| 接电源 | 5 | 04:58 | 05:02 – 05:14 |
| 电池 | 3 | 04:58 | 05:27、06:17、**06:56** |

漂移两小时，而日志里依然写着成功。本工具用 `caffeinate -u` 强制真实唤醒，随即把屏幕
关回去，免得凌晨四点亮一屏。

## 安装

在 Codex 里：

```bash
codex plugin marketplace add https://github.com/unnamedhoead/codex-anchor-mac.git
codex plugin add codex-anchor-mac@codex-anchor-mac
python3 ~/.codex/plugins/cache/codex-anchor-mac/codex-anchor-mac/*/scripts/register_mcp.py
```

然后开一个**新的** Codex 会话，让它打开锚点面板。

第三行不是可选项，也不是你装错了：Codex 会安装插件并标记为 enabled，但**不会**读
`mcp.json` 去启动 server——少了这一步，插件装上了而工具永远不出现。插件升级后要重跑一次，
因为缓存路径里带版本号，旧注册会指向一个已经不存在的目录。

装插件就等于装好了定时任务：面板首次打开时会创建 `~/.codex-anchor/`、装好 launchd 任务，
并通过 macOS 标准授权弹窗询问是否设置每日唤醒。最后这步**可以拒绝**：任务照常运行，只是
在没插电、机器睡着的夜里会迟到。

不用 Codex 的话，任务本身也能独立工作，只是没有面板：

```bash
git clone https://github.com/unnamedhoead/codex-anchor-mac.git ~/codex-anchor-mac
cd ~/codex-anchor-mac && ./setup.sh
```

两条路都装进 `~/.codex-anchor/`，共用一份日志和一份计划。

## 控制面板

![控制面板](docs/panel.png)

面板渲染在 Codex 内部，不是浏览器。可以：

- 改触发时间，时区自选
- 启用或停用任务
- 手动触发一次
- 查看最近 15 次运行
- 在 English 和中文之间切换界面语言
- 插件升级后副本过期时，一键修复

改时间会同时同步 launchd 任务、`config.json` 和 `pmset` 唤醒，三者不会各自跑偏。

面板通过 MCP 工具调用访问后端，而不是 HTTP——因为 Codex 会拦截沙箱面板对 localhost 的
访问，即使显式声明了来源也一样（[openai/codex#45913](https://github.com/openai/codex/issues/45913)）。

## 时区

launchd 只认系统时钟。面板写入计划前会换算成系统本地时间，所以
「`04:30 Asia/Shanghai`」在你的机器上会变成对应的本地时刻。

下拉框里是 58 个时区，不是全部 598 个。去重的键是**（1 月偏移, 7 月偏移）**这一对，
所以每一项代表一套真实的规则、含夏令时在内——若改用「当前偏移」去重，
Europe/London 和 Africa/Abidjan 会被并成一项，而它们有半年时间是不同的。
你本机的时区始终在列表里。

如果系统时区之后变了——你出差了——面板会显示横幅，点一次重新同步即可。避免把时间设在
你所在地区的夏令时跳变区间（通常是 01:00–03:00），那个墙钟时刻在跳变当天可能不存在。

## 工作原理

`anchor.sh` 对 ChatGPT.app 内置（或 `PATH` 上）的 Codex CLI 执行一次 `codex exec`：

- `-s read-only` —— 显式沙箱，确保无人值守的任务不会继承宽松的全局配置
- `--ephemeral` —— 不留 session 历史
- 240 秒看门狗 + 目录锁
- 提示词是「读取本 README 并输出前 100 字」，顺便充当健康检查：日志尾部不对劲，
  就说明有问题

日志写入 `anchor.log`：

```
2026-10-07 05:02:18 +0800  OK  exit=0 22s tz=CST+0800  tail: # codex-anchor-mac ...
```

**它必须以 ChatGPT 订阅身份认证**（`~/.codex/auth.json` 里 `auth_mode = chatgpt`）。
OpenAI API key 是单独计费的，走 API 根本不会启动订阅的窗口。

## 开发

```bash
./test.sh
```

48 项检查，全部针对临时目录里的桩二进制运行，**不会发出任何真实请求，也不会
开启额度窗口**。覆盖 `anchor.sh` 的成功 / 空输出 / 失败 / 看门狗 / 找不到二进制 /
加锁等路径，时区换算，stdio 上的 MCP 协议表面，以及各项守卫（TCC 拒绝、plist 严格 XML、
sudoers 语法、清单一致性、面板不引用任何外部源）。
CI 在 `macos-latest` 上运行。

## 已知限制

- 关机的 Mac 无法被唤醒。`pmset` 只能从睡眠状态唤醒。
- 电量过低时 macOS 可能跳过计划唤醒。
- 注销或切换用户会卸载 LaunchAgent。锁屏不影响。
- DarkWake 的处理方式**除作者本机外未经独立验证**。如果你的日志出现
  `[machine slept mid-run; anchor landed late]`，说明在你那里没生效——请附上电源日志
  提 issue。
- 窗口行为由 OpenAI 服务端决定，随时可能变。权威的重置时间以 Codex 里的 `/status` 为准。

## 卸载

```bash
./uninstall.sh
```

## 许可

MIT，见 [LICENSE](LICENSE)。
