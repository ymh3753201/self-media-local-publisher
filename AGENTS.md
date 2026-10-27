# 自媒体本地发布助手：项目约定

给用户的开发报告使用简单中文，说明已完成内容、验证结果和实际限制。

## 产品范围

本项目是独立的 Python 本地工具。默认 `standalone`，规划、素材检查、平台规则、封存和人工审核记录均由本项目实现。默认平台为抖音、小红书、B站、微信视频号和 YouTube。

不要导入或调用电脑外的 `publisher-agent`、`social-auto-upload` 来冒充独立实现。Hermes 只读规则兼容是用户主动配置的可选模式，不是新用户的安装前提。

## 工作目录和隔离

- 命令入口：`python3 scripts/publisherctl.py`，安装后为 `publisherctl`。
- 每次发布任务先运行 `doctor --json`、`context --json`；浏览器审核另检查 `doctor --browser --json`。
- 运行产物、报告、封面、素材副本、审核证据和私人备份都放在本项目 `.publisher-runs/`。
- 私人配置使用被忽略的 `config/adapter.local.json`。不得提交账号、Cookie、密码、Token、OAuth Secret、登录状态和真实私人素材。
- 不修改、启动、停止、接管 Hermes Agent，也不修改其 Profile、SOUL、Skills、会话、网关或计划任务。
- 不修改、重装、重置用户电脑外的上传工具或登录环境。
- 兼容模式只读 SOUL 和发布 Skill 的内容指纹；不能复制私人 Profile 到公开项目，不读取账号或授权配置。

## 素材与封面

必须提供可解析视频（mp4/mov/mkv）和匹配的 UTF-8 SRT。字幕是事实依据，不得根据文件名、封面或模板补造产品能力、数据和承诺。字幕覆盖不足需要说明核对结果。

竖版封面：9:16、3:4、4:3。横版封面：16:9、4:3、3:4。三张共享人物/主体、标题、内容、配色和设计风格。

Codex 遇到缺封面时，加载内置 imagegen Skill 并调用 image_gen；不自行切换需要 API Key 的 CLI。最终封面保存在运行目录，逐张检查脸、手、文字、裁切、安全区。中文标题优先确定性排版。生图次数和费用遵守用户当次授权。

## 计划和人工确认

1. `inspect` 检查素材；`plan` 仅生成 draft。
2. 根据完整字幕优化平台文案；明确 B站分区、YouTube 受众和可见性；原创与 AI 内容声明分开。
3. 实际检查文案和封面后运行 `seal --content-reviewed --covers-reviewed`；覆盖不足时填写 `--subtitle-note`。
4. `verify` 必须为 `ready_for_review`；向用户展示平台、封面、文案、声明和可见性。
5. 等用户明确确认本轮 `review_approval_phrase`，再执行 `review-start`。命令只保存确认和冻结记录，本身不启动浏览器。
6. 不修改开始审核的计划；素材或文案需修改时创建新任务。旧版适配层计划必须从原始素材重新生成。

## Ego 浏览器流程

浏览器能力来自使用者环境中的 ego-browser 技能，不由本 CLI 安装或代理。缺少能力时停在本地合格计划，不换用旧 Patchright、普通 Chrome 或其他环境。

- 先读取本轮技能指南并列出 Task Spaces，检查 `publisher:` 或同平台既有操作；冲突时停止该平台并报告。
- 每个平台一个 `codex-publisher:<run-id>:<platform>` 空间；创建后 `review-bind` 保存数字 ID。同平台复用原 ID。
- 不 claim、take over、close 或 complete 其他前缀空间。
- 遵循 snapshot → 分组操作 → 页面读回。读取 `codex_adapter.platform_ui_contracts` 并以实际页面核对。
- B站清理自动带入的标题、简介和标签，分区按本期内容选择；视频号未要求位置时清除自动城市。
- YouTube 自定义封面/Shorts 能力以当前 Studio 可用功能为准，不支持时标 `manual_required`，不能把文件比例正确当成上传成功。
- 登录、验证码、OAuth、2FA、风控、旧草稿、AI/原创协议、版权或管理员验证立即 handoff 原空间。用户明确“继续”前不能重新取得控制。
- 上传和字段读回完成后 handoff 原空间，使用 `review-record` 记录证据。证据只能包含必要字段，不保存原始 DOM、浏览器存储或凭据。
- 默认最终发布、发表、立即投稿、Publish、Done、保存草稿由用户操作；不得将开发或开源授权当成平台提交授权。

## 状态与验证

本地 `ready_for_review` 代表计划合格；平台 `review_ready` 代表上传/填表/读回及交接完成。`manual_review_finished` 仅依据用户明确确认的人工提交；不能据测试通过、返回码、开窗、关窗推断发布成功。

结构探索先使用已安装的 codebase-memory Skill 并检查覆盖；索引缺失或陈旧时回到实际源码。字符串与非代码文件使用 rg。修改使用补丁，保留已有工作。

变更验证：`python3 -B -m unittest discover -s tests -v`。开源前运行 `python3 scripts/check_public_files.py`，检查待提交文件、许可证、打包和隔离安装。不要自动重试结果不明的远程创建、提交或发布操作。
