# codex-quota-warmup

每天凌晨 04:58 自动向 Codex 发一次极小的请求，把 ChatGPT 订阅的 5 小时额度窗口
锚定在你需要的位置上，这样从早上 8 点开工起就不用中途空等三小时。

## 为什么是 04:58，而不是 4:00

额度窗口是**由首条消息锚定的 5 小时固定块**，块一旦开始，边界就不动了。
关键在于：warmup 只有在「当前没有活动窗口」时才会开新块——所以它真正的作用
不是省额度，而是**把窗口边界往前挪，让更多边界落在你的工作时段里**。

按 8:00 起床、约 2 小时烧完一个窗口来算：

| warmup | 窗口边界 | 8:00 之后 | 工作时段内摸到的窗口数 |
|---|---|---|---|
| 不设 | 8:00 / 13:00 / 18:00 | 10:00 烧完 → 空等到 13:00 | 2 |
| 04:00 | 4:00 / 9:00 / 14:00 / 19:00 | 8:00-9:00 只用 1 小时就翻窗，浪费半块额度；11:00 烧完 → 空等到 14:00 | 3（但浪费） |
| **04:58** | **5:00 / 10:00 / 15:00 / 20:00** | 8:00 开工拿到整块未动的额度，**10:00 刚烧完就无缝翻新窗口** | 3 |

公式：

```
warmup 时间 = 起床时间 + 烧完一个窗口需要的时间 − 5h
            = 8:00 + 2h − 5h = 5:00
```

如果你的起床时间或消耗速度变了，用这个公式重算，然后改 `com.hoead.codex-warmup.plist`
里的 `Hour`/`Minute` 和 `install.sh` 里的 `WAKE_TIME`，重跑 `./install.sh`。

## 安装

```bash
./install.sh     # 装 LaunchAgent + 配 pmset 定时唤醒（会要 sudo）
```

`install.sh` 做两件事：

1. 把 LaunchAgent 装到 `~/Library/LaunchAgents/`，每天 04:58 触发
2. `sudo pmset repeat wake MTWRFSU 04:55:00` —— **launchd 自己不会唤醒睡着的
   Mac**，靠这行把机器叫醒

### 第 2 步在这台机器上是保险，不是必需

本机实测的电源配置（`pmset -g custom`）：

| 供电状态 | `sleep` | 含义 |
|---|---|---|
| 接电源 | `0` | **系统根本不睡**，launchd 04:58 直接触发，与 pmset 无关 |
| 用电池 | `1` | 闲置 1 分钟就睡，**这时才需要 pmset 唤醒** |

所以只要晚上插着电，不用开任何「永不睡眠」——接电源时它本来就是。
pmset 那行是为「某晚忘了插电」准备的，装上无害。

如果你改过 AC 的睡眠设置，用 `pmset -g custom` 重新确认。

## 卸载

```bash
./uninstall.sh   # 卸 LaunchAgent + pmset repeat cancel
```

## 每天早上检查昨晚跑没跑成

```bash
tail -5 ~/codex-quota-warmup/warmup.log
```

`OK` 那行带耗时和模型回复的尾部，能确认是模型真的答了，不只是进程正常退出：

```
2026-09-29 04:58:03 +0800  OK    exit=0 9s  tail: # codex-quota-warmup 每天凌晨 04:58 自动向 Codex 发一次极小的请求...
```

想确认定时任务本身的状态：

```bash
launchctl print gui/$UID/com.hoead.codex-warmup | grep -E 'state|runs|last exit code'
pmset -g sched
```

## 手动跑一次

```bash
./warmup.sh; tail -3 warmup.log
```

⚠️ 这会**立刻开一个 5 小时窗口**（边界重置到此刻），所以别在工作时段随手跑。

## 实现上的几个决定

- **用 ChatGPT.app 内置的 codex，不用 API。** 二进制在
  `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`，
  配合 `~/.codex/auth.json` 里的 `auth_mode = chatgpt`。这一点是整件事的前提：
  **OpenAI API key 是单独计费的，走 API 根本不会启动订阅的 5 小时窗口。**
  换机器或换安装方式时用 `CODEX_BIN=... ./warmup.sh` 覆盖路径。
- **不覆盖模型。** 用 `~/.codex/config.toml` 里的默认模型，只把 reasoning effort
  压到 `low`。网上的方案建议换成 mini 模型省钱，但换模型有可能落到不同的
  rate-limit bucket，那 warmup 就白跑了——用同一个模型才能保证打中同一个额度桶。
- **显式 `-s read-only`。** 你的全局 config 是 `sandbox_mode = danger-full-access`
  + `approval_policy = never`，无人值守的定时任务绝不该继承这个。
- **`caffeinate -i` 包住请求。** pmset 唤醒之后 Mac 随时可能又睡回去，
  尤其是合盖状态，不加这个请求可能中途被掐断。
- **`--ephemeral`**，不往 session 历史里留垃圾。
- **240 秒超时 + 目录锁**，防止网络卡住时进程挂着不退，或手动跑和定时跑撞在一起。

## 为什么这个文件夹不能放在 ~/Documents

放过，翻车了。`~/Documents`、`~/Desktop`、`~/Downloads` 等目录受 macOS TCC 保护，
**launchd 派生的进程没有这些目录的访问权**，脚本会以

```
/bin/bash: .../warmup.sh: Operation not permitted
```

失败，exit code 126。坑在于：安装时一切正常（你的终端有权限），只有凌晨那一跑
会静默失败，而且 `warmup.log` 压根不会生成，看起来像"任务没触发"。

隔离实验（同一 plist 结构，只改目录）：

| 脚本位置 | launchd 执行结果 |
|---|---|
| `~/Documents/tcctest/probe.sh` | `Operation not permitted`, exit 126 |
| `~/.tcctest/probe.sh` | 正常输出, exit 0 |

`install.sh` 现在会主动拦住这六个目录并报错退出，不会让你再装出一个每晚静默
失败的定时任务。

## 已知限制

- **别把这个文件夹移回 ~/Documents / ~/Desktop / ~/Downloads**（见上一节）。
- **注销或切换用户会卸载 LaunchAgent**，锁屏不影响。睡前锁屏就行，别注销。
- **Mac 完全关机时不会唤醒。** `pmset` 只能唤醒睡眠状态的机器。
- **电量过低时 macOS 可能跳过计划唤醒。** 想稳就插电（插电时本机压根不睡）。
- **靠 pmset 唤醒时，机器会在任务结束后睡回去**，`caffeinate -i` 只保住请求
  这段时间，这是有意为之。
- **`pmset repeat` 全局只能有一套重复计划**，`install.sh` 会检测已有计划并让你确认。
- 窗口的具体行为由 OpenAI 服务端决定，随时可能变。真实的重置时间以 Codex 里的
  `/status` 为准。
- **`-c` 覆盖参数（`notify=[]` 等）没有经过离线验证。** `codex doctor` 不校验
  `-c`，而唯一的校验途径 `codex exec --strict-config` 必须发真实请求。这几个值
  本身都很保守（`approval_policy` 用的就是 config 里的原值，`low` 是文档里的
  合法档位），万一真挂了，日志里会是 `FAIL` 加上 codex 的报错原文。
  **第一次手动跑之后请看一眼 `warmup.log` 确认是 `OK`。**
