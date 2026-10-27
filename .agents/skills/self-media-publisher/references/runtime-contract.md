# 本地运行、人工审核和证据

## 文件和冻结规则

每个任务在 `.publisher-runs/<run-id>/` 保存：

```text
input/                   字幕和封面副本（原视频只读引用，不复制大文件）
assets.json              素材路径与 SHA-256 内容指纹
publish_plan.json        可编辑计划；封存后修改会使验证失败
publish_preview.md       给用户阅读的文案与封面预览
manifest.json            最后写入的一致性标记
review.json              确认、平台空间和审核记录；开始审核后才出现
```

视频使用原始绝对路径，程序只读；不能把它称为文件系统级的只读保护。源字幕/封面和副本均验证内容指纹，素材被移动、删除或替换后应重新生成任务。

新任务使用本项目自带规则。可选 Hermes 模式只读 SOUL 和相关发布 Skill，不读取账号配置。代码、配置、技能和规则的内容变化会让尚未开始审核的旧计划失效，单纯修改时间变化不会。

`review-start` 保存人工确认并冻结本轮规则与配置；后续继续核对原计划和素材。规则更新不在中途静默改写文案。审核期间不要升级或替换运行代码；版本变化后应先核对记录再恢复。需要换素材、文案或平台时生成新任务。

SHA-256 和确认短语用于防止误操作及识别变更，不是密码、数字签名，也不能防止具有本机文件写权限的人故意重写全部记录。

## Ego 空间

首先加载使用者已安装的 ego-browser 技能，执行其当前指南。缺少该能力时保留本地计划并说明人工事项。`doctor --browser` 只检查命令可调用，不验证登录、平台页面或技能是否已被 AI 加载。

每个平台独立空间，名字必须为 `codex-publisher:<run-id>:<platform>`。创建后立即登记：

```bash
publisherctl review-bind --plan <计划> --platform douyin \
  --space-id <数字ID> --space-name codex-publisher:<run-id>:douyin
```

先列出已有空间检查冲突，禁止操作 Hermes 的 `publisher:` 或其他工具的空间。同平台一直使用原 ID。登录、验证码、AI/原创协议、版权、旧草稿、风控和最终验收必须 handoff 原空间；用户明确“继续”后才恢复控制。

CLI 校验的是操作者提交的记录与计划是否一致，不直接连接 Ego，也不能独立证明页面证据真实。操作者仍须从实际页面读取，不得从计划复制数值冒充读回。

## 页面证据

证据是小型 JSON，保存在本轮运行目录。`review_ready` 记录需要以下实际信息：

- 已绑定的 `space_id`、`browser_backend: ego` 和当前 `plan_sha256`；
- 本次上传视频的 `video_sha256`、所选封面的 `cover_sha256`；
- `video_uploaded`、`cover_uploaded`、`required_fields_readback`、`stopped_before_publish`、`handoff` 都为 true；
- `fields`：页面实际读回的 title、description、tags 或 hashtags；B站还含 category，YouTube 还含 audience 和 visibility；
- `declarations_reviewed: true`：原创、AI、版权等平台声明已按事实检查；若计划 AI 状态未知，`ai_declaration_required` 必须明确为 false，否则交由用户确认并重新生成有明确声明的计划。

平台不支持计划封面上传，或声明/必填项未完成时，记录 `manual_required` 和 `reason`，不能勾选不存在的成功证据。格式参考仓库 `examples/review-evidence.example.json`；示例不是真实证据。

```bash
publisherctl review-record --plan <计划> --platform douyin \
  --status review_ready --evidence <本轮证据JSON>
publisherctl review-status --plan <计划> --json
```

`blocked`、`failed` 和 `manual_required` 至少需同一 space_id 与原因。用户明确确认已在原页面人工提交后，可从 `review_ready` 转为 `manual_review_finished`，证据为 space_id、user_confirmed: true、confirmation（用户原意的简短记录）。不把它解释为系统独立核验了公开上线。

不保存原始 DOM、Cookie、密码、Token、OAuth Secret 或整个浏览器会话；不要把页面地址上的授权参数粘进原因。CLI 会拒绝部分敏感特征，但不代替操作者检查。
