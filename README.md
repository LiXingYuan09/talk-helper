# talk helper

在已验证的 Windows 微信桌面版中，为选定聊天里对方发送的普通文字显示逐条建议卡片。原有聊天界面、头像、昵称及媒体消息由微信继续处理；建议只供参考，不会自动发送。

## 下载与使用

下载 [`TalkHelper-Portable-v13r2.7.zip`](talk-helper-settings/TalkHelper-Portable-v13r2.7.zip)，解压后阅读包内 `README.md`。目前只支持已核对构建指纹的微信 **4.1.13.65 / 4.1.15.13 x64**；不同安装路径可以使用，同版本但二进制不匹配的构建会拒绝加载。另一台电脑尚未现场验证。

先登录微信，运行 `TalkHelper-Native-v13.exe`。在微信输入栏右键 talk helper 打开设置，填入自己在 DeepSeek 的 API Key，并选择要启用的联系人或群聊。密钥保存在当前 Windows 用户的凭据管理器中。程序只将已启用聊天的普通文字发给 DeepSeek 官方接口，不使用 OCR，不自动发送回复。

## 源码

- [`talk-helper-settings/src`](talk-helper-settings/src)：原生启动器、微信内嵌界面和消息行排版。
- [`talk-helper-settings/worker`](talk-helper-settings/worker)：消息核对、设置、建议生成及测试。
- [`jev-chat-desktop/core`](jev-chat-desktop/core)：DeepSeek 分析与回复生成核心。
- [`jev-chat-desktop/app/settings.py`](jev-chat-desktop/app/settings.py)：连接设置及凭据读取。
- [`talk-helper-settings/build.ps1`](talk-helper-settings/build.ps1) 和 [`talk-helper-settings/worker.spec`](talk-helper-settings/worker.spec)：Windows 构建入口。构建脚本当前需要本机 MSYS2 MinGW64 路径；便携包不需要编译环境。

详细功能与限制见 [`talk-helper-settings/README.md`](talk-helper-settings/README.md)，验证记录见 [`talk-helper-settings/VALIDATION.md`](talk-helper-settings/VALIDATION.md)。发布包采用默认配置，不包含聊天选择、关系档案、聊天记录或 API Key。第三方声明见 [`talk-helper-settings/THIRD_PARTY_NOTICE.md`](talk-helper-settings/THIRD_PARTY_NOTICE.md)。

这是对特定微信构建的独立兼容实现，并非微信官方插件。微信更新后可能需要重新适配，请勿在未验证版本上强制加载。
