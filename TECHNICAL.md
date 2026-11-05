# VCVR — Vibe Coding Voice Remote (Windows)

把**谷歌 Chromecast 遥控器**变成 Vibe Coding 的语音输入 + 快捷键外设。
基于 [ZSTDJan/windows-remote-mic-app](https://github.com/ZSTDJan/windows-remote-mic-app)
（无线麦 Win 版）源码分叉，修掉停止缺陷，并内置一套适合写代码的按键布局。

```
VCVR  =  Vibe Coding Voice Remote
```

---

## 一、现在能不能用

能。当前状态：

| 项目 | 值 |
|---|---|
| 程序 | `VCVR 1.0.104.exe`（安装目录） |
| 遥控器 | `Chromecast Remote` · VID `18D1` / PID `9450` / REV `0110` |
| 豆包 | `v1.0.0.23`（已适配） |
| 虚拟声卡 | VB-CABLE（`CABLE Input` 播放 / `CABLE Output` 录音） |

---

## 二、怎么用

1. **以管理员身份**启动 `VCVR 1.0.104.exe`
   （必须提权，否则接收按键的辅助进程起不来）
2. 光标点进任意能输入文字的地方
3. **按住遥控器语音键**说话，松开 → 豆包把语音转成文字上屏

### 按键映射（出厂默认）

| 遥控器按键 | 动作 |
|---|---|
| 语音键（中间黑键） | 按住说话（豆包转写） |
| 上 / 下 | **鼠标滚轮上 / 下**（长按连续滚） |
| 左 / 右 | 方向键 ← / → |
| 侧边音量 + / − | 方向键 ↑ / ↓ |
| 中心圆（确定） | 回车 |
| 返回 | 退格 |
| 主页 | 显示桌面 |
| 电源 | Esc |
| 静音 | 系统静音 |
| Netflix | Ctrl+V（粘贴） |
| YouTube | Ctrl+C（复制） |
| 输入源 | 禁用 |

**滚轮手感**：按一下 = 滚 1 格；长按 0.35 秒后开始每 60ms 滚一格（约 16 格/秒）。

改映射：程序左侧 **按键** 页，每列单击/双击/长按可分别设置；保存后立即生效。

> ⚠️ 不要把"长按"和"连发"混用：某个键一旦配置了长按动作，长按就只触发一次，
> 不会再连发。想要连发就把该键的长按设为"未设置"。

---

## 三、豆包版本兼容（重要）

VCVR 通过 Frida 注入豆包进程，钩住它 `ImeService.exe` 里的键盘回调，
把注入的快捷键伪装成物理按键（豆包只认真实按键，纯 `SendInput` 会被丢弃）。
这套钩子按**版本**硬编码三个 RVA + 文件哈希，所以豆包升级后需要适配。

### 当前支持

| 豆包版本 | 状态 |
|---|---|
| v0.9.0.0 / v0.9.1.22 / v0.9.2.7 / v0.9.3.20 / v1.0.0.23 | 内置表支持 |

### 豆包升级了怎么办（两步，不需要重新编译）

1. 双击仓库根目录的 `适配新豆包版本.bat`
2. 重启 VCVR

脚本会从当前豆包目录算出 **3 个文件哈希 + 3 个 RVA + 2 段签名字节**，
写进：

```
%LOCALAPPDATA%\RemoteMic\RC003\doubao_profiles.json
```

程序启动时自动读取并合并进内置表（文件损坏会整段忽略，不会导致起不来）。

### 怎么判断是不是版本问题

看 `%LOCALAPPDATA%\RemoteMic\RC003\logs\app.log`：

| 日志 | 含义 |
|---|---|
| `Doubao voice physicalizer ready for configured shortcut` | 正常 |
| `Doubao voice physicalizer unavailable: status=unsupported_version` | 版本不支持，跑一次适配脚本 |
| `result=sent_once` | 停止走 RPC，正常 |
| `result=send_failed_shortcut_fallback` | RPC 失败但热键兜底成功（可接受） |

---

## 四、相对上游的改动

上游是 Cython 编译分发，本仓库是源码分叉，共 5 处改动：

### 1. 修复「停止录音」失败（根因）

`doubao_rpc.py` 挑选 `rpc.dll` 时按**版本号倒序**取磁盘上最新安装的那份，
而不是**实际正在运行**的那份。多版本共存时（如装了 0.9.3.20 又下载了 1.0.0.23），
会用错版本的 RPC 布局去和当前服务通信，返回非零 → `send_failed`。

修复：新增 `_active_version_directory()`，从
`HKLM\SOFTWARE\DoubaoIme\VersionDir` 读真实版本并排在候选首位。

### 2. 停止增加热键兜底

`chromecast_voice_host.py`：RPC 停止失败时，补发一次带标记的 RAlt
（豆包免按模式的本质就是热键 toggle），避免录音卡住、后续会话全被拒。

### 3. 恢复鼠标滚轮动作

上游把 `mouse_wheel_*` 悄悄改写成 PageUp/PageDown。本分支恢复真正的
`SendInput` 滚轮事件（`win32_input.send_mouse_wheel`），并让它在 UI 里可选。

### 4. 滚轮支持长按连发

`REPEATABLE_ACTIONS` 加入滚轮，重复间隔 60ms；同时把"只有特定按钮才允许连发"
的白名单改为只看动作类型。

### 5. 出厂按键布局 + 改名

默认映射改为上表；产品名改为 `VCVR`，版本号 `1.0.104`。

### 6. 版本表可外挂

新增 `doubao_profiles.json` 加载器，适配新豆包版本不再需要重新编译。

---

## 五、构建

```bat
cd apps\windows\rc003
python -m PyInstaller ^
    build\RemoteMicRC003.spec --distpath dist --workpath build\pyinstaller-work --noconfirm
```

产物：`dist\RemoteMicRC003\VCVR 1.0.104.exe` + `dist\RemoteMicRC003HidHelper.exe`

> 当前为**纯 Python 构建**（机器上没有 MSVC）。功能与上游的 Cython 版一致，
> 只是少了源码加密、启动略慢几十毫秒。要编译版就装
> "Microsoft C++ Build Tools"（约 2–4 GB）后跑 `build\prepare-cython-core.py`。

---

## 六、常见问题

| 现象 | 处理 |
|---|---|
| 豆包不出字 | 豆包输入法麦克风要选 `CABLE Output (VB-Audio Virtual Cable)` |
| 按语音键没反应 | 程序必须**以管理员身份**运行；设备页显示"已连接" |
| 停止后无法再次录音 | 见第三节，跑一次版本适配脚本 |
| 滚轮长按不连发 | 该键的"长按"动作被设置了，改回"未设置" |
| 找不到遥控器 | 蓝牙设置里重新配对，按任意键唤醒 |

---

## 七、目录

```
<工作区>\
├─ VCVR\                          ← 运行目录（以管理员启动里面的 exe）
└─ remote-mic-fork\               ← 本仓库（源码）
│   ├─ apps\windows\rc003\src\ovb_rc003\   核心模块
│      ├─ tools\doubao_profile.py             新豆包版本参数扫描器
│   ├─ tools\adapt_doubao.py               一键生成适配 JSON / 改源码
│   ├─ docs\豆包版本适配说明.md             版本适配详细说明
│   └─ 适配新豆包版本.bat                   豆包升级后双击它
├─ build-venv\                    ← 构建环境（Python 3.12 + PyInstaller）
└─ rea-tools\                     ← 早期自研链路与诊断脚本（历史留档）
```

配置与日志：

```
%LOCALAPPDATA%\RemoteMic\RC003\
├─ config.json                设备选择、输出端点、语音程序
├─ key_bindings.json          按键映射
├─ doubao_profiles.json       豆包版本适配表（可外挂）
├─ bridge-runtime-status-s1.json  运行状态快照
└─ logs\app.log               诊断日志
```
