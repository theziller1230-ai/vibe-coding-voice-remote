# VCVR — Vibe Coding Voice Remote

把一只 **谷歌 Chromecast 遥控器**（或小米遥控器 2 Pro）变成 Windows 上的
**语音输入 + 快捷键外设**：按住遥控器语音按键说话，豆包输入法把语音转成文字上屏；
按键可以自定义成快捷键、滚轮、打开程序等。

当前正式版为 **1.0.104**（Windows 便携版，免安装）。

---

## 一、下载与校验

- 发布页：[`v1.0.104`](https://github.com/theziller1230-ai/vibe-coding-voice-remote/releases/tag/v1.0.104)
- 下载包：`RemoteMicRC003-1.0.104-portable-unsigned.zip`
- 包内两个产物：`VCVR 1.0.104.exe`（主程序）与 `RemoteMicRC003HidHelper.exe`（权限助手）
- 下载后请用包内的 **`SHA256SUMS.txt`** 校验，哈希对不上就不要运行
- **完整解压**到一个固定目录（不要在压缩包里直接运行）
- **从旧版升级**：旧版主程序名是 `无线麦 win版 <版本号>.exe`；新版用
  `VCVR 1.0.104.exe`，程序会自动识别旧名并迁移开机自启项
- 更新是**手动替换**：先**完全退出**旧版（托盘图标右键 → 完全退出），再解压覆盖

> 更详细的操作步骤参见 [使用说明](apps/windows/rc003/README.md)，
> 代码结构与构建方式参见 [开发者文档](apps/windows/rc003/README.md)。

---

## 二、准备（一次性）

| 项目 | 说明 |
| --- | --- |
| Windows 10 / 11 x64 | |
| 蓝牙 | 遥控器需与电脑配对 |
| 豆包输入法 | [官网下载](https://www.doubao.com/)，建议 1.0.0.23 或更高 |
| VB-CABLE 虚拟声卡 | [VB-Audio](https://vb-audio.com/Cable/)，免费 |

**配对遥控器**：设置 → 蓝牙和其他设备 → 添加设备 → 选择 `Chromecast Remote`
或 小米遥控器2 Pro（遥控器长按配对键进入配对）。

**接音频线**（这一步最容易配错）：

1. 安装 VB-CABLE 后重启电脑
2. 程序里把**语音输出端点**选成 `CABLE Input (VB-Audio Virtual Cable)`
3. 豆包输入法的**麦克风**选成 `CABLE Output (VB-Audio Virtual Cable)`

两端必须配对：程序往 `CABLE Input` 写，豆包从 `CABLE Output` 读。

---

## 三、使用

1. **以管理员身份**运行 `VCVR 1.0.104.exe`
   （必须提权，否则接收遥控器按键的助手进程起不来）
2. 光标点进任意能输入文字的地方
3. 按住**语音按键**说话，松开 → 文字上屏

**真实输入自检**：打开**记事本**，按住语音按键说一句话，松开后应有文字上屏。
这一步通过，说明整条链路是通的。

**出厂默认按键**（可在程序「按键」页逐键修改）：

| 遥控器按键 | 动作 |
| --- | --- |
| 语音键 | 口述开始 / 结束 |
| 上 / 下 | 鼠标滚轮 |
| 左 / 右 | 方向键 ← / → |
| 音量 + / − | 方向键 ↑ / ↓ |
| 确定 | 回车 |
| 返回 | 退格 |
| 主页 | 显示桌面 |
| 电源 | Esc |
| 静音 | 系统静音 |
| Netflix / YouTube | Ctrl+V / Ctrl+C |
| 输入源 | 禁用 |

---

## 四、豆包升级后

钩子按豆包版本适配，豆包升级后跑一次仓库根目录的 `适配新豆包版本.bat`，再重启程序即可。
详见 [`docs/豆包版本适配说明.md`](docs/豆包版本适配说明.md)。

---

## 五、常见问题

| 现象 | 处理 |
| --- | --- |
| 豆包不出字 | 豆包麦克风要选 `CABLE Output`；程序输出端点要选 `CABLE Input` |
| 按语音键没反应 | 程序要**以管理员身份**运行；设备页显示「已连接」 |
| 界面提示未就绪 | **未就绪提示，按页面说明处理**，每条提示都对应一个可点的修复动作 |
| 语音通道不可用 | 多按几次语音按键唤醒遥控器；仍不行就重启程序 |
| 停止后不能再录 | 跑一次 `适配新豆包版本.bat` |
| 滚轮长按不连发 | 该键的「长按」动作被设置了，改回「未设置」 |
| 找不到遥控器 | 蓝牙里重新配对，按任意键唤醒 |

日志：`%LOCALAPPDATA%\RemoteMic\RC003\logs\app.log`

---

## 六、许可与致谢

按 **GPL-3.0-only** 发布，见 [LICENSE.md](LICENSE.md) 与 [COPYRIGHT.md](COPYRIGHT.md)。

本项目是开源项目的衍生作品：

- [`nijez/open-voice-bridge`](https://github.com/nijez/open-voice-bridge) — Windows RC003 客户端原始实现
- [`ZSTDJan/windows-remote-mic-app`](https://github.com/ZSTDJan/windows-remote-mic-app) — 无线麦 Win 版（中文发行版）
- [`HD838A/remote-mic-app`](https://github.com/HD838A/remote-mic-app) — 无线麦 macOS 版

第三方组件与素材边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[ASSET_LICENSES.md](ASSET_LICENSES.md)。
