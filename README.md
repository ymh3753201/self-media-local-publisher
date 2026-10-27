# 自媒体本地发布助手

把一个视频和字幕整理成抖音、小红书、B站、微信视频号、YouTube 的差异化发布计划，再通过 AI 的 Ego 浏览器技能完成上传填表、页面核对和人工交接。

**0.1.0 为开发预览版。**本地规划、校验和审核记录已独立实现；浏览器上传需要使用者环境提供 Ego 与相应 AI 技能。最后的发布按钮默认由使用者点击。本版本不包含无人值守上传服务，不承诺各平台当前页面都已完成真实回归。

## 可以做什么

- 检查视频、SRT 时间轴、实际字幕覆盖和三比例封面。
- 按字幕摘录生成五平台草稿；文案可以由你或 AI 进一步编辑。
- 检查标题、简介、标签、分区、受众、可见性及统一封面标题。
- 将素材和规则与计划绑定，修改后要求重新核对。
- 记录每个平台的 Ego 空间、页面读回、人工交接和完成状态。
- 默认独立运行，不要求安装 Hermes、publisher-agent 或 social-auto-upload；可选读取自己的 Hermes 发布规则。

生成器不调用付费模型，也不会凭空推断字幕之外的工具能力。“原创”与“是否含 AI 内容”分开记录。文件检查通过仍需实际看封面、核对文案和平台页面。

## 安装

需要 Python **3.11 或更新版本**和 **FFmpeg**（含 ffprobe）。本地验证平台为 macOS；仓库工作流配置 Ubuntu 自动测试，其他系统需要自行验收。

```bash
git clone https://github.com/ymh3753201/self-media-local-publisher.git
cd self-media-local-publisher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

macOS 使用 Homebrew 时可通过 `brew install ffmpeg` 安装媒体检查工具。也可以从 FFmpeg 官方发行渠道安装；安装后确认 `ffprobe -version` 能运行。

安装后运行 `publisherctl`。在源码目录里也可以不安装 Python 包，直接使用 `python3 scripts/publisherctl.py`。Python 运行部分没有第三方包依赖；打包需要 setuptools。

```bash
publisherctl doctor --json
publisherctl context --json
```

`doctor` 返回 `ready` 表示本地规划依赖可用。`publisherctl doctor --browser --json` 额外检查 Ego 命令。浏览器功能还需你的 AI 环境已安装并能加载 ego-browser 技能；本项目不安装浏览器、不迁移登录状态、不绕过登录或验证码。

## 第一次生成计划

准备同一视频的 mp4/mov/mkv 和 UTF-8 编码 SRT。封面三张必须是同一设计：

| 视频 | 封面比例 |
|---|---|
| 竖版 | 9:16、3:4、4:3 |
| 横版或方形 | 16:9、4:3、3:4 |

在 Codex 中缺封面时可使用内置 imagegen 生成；任何生成费用和次数以当次授权为准。本地 CLI 自身不生成图片。封面标题、人物、配色与主题应统一，生成后实际检查错字、手脸、主体裁切和安全区。

以下以横版视频为例，替换尖括号内容后执行：

```bash
publisherctl inspect --video '<视频绝对路径.mp4>' --subtitle '<字幕绝对路径.srt>' --json

publisherctl plan \
  --video '<视频绝对路径.mp4>' --subtitle '<字幕绝对路径.srt>' \
  --cover '<16比9封面.png>' --cover '<4比3封面.png>' --cover '<3比4封面.png>' \
  --cover-title '统一封面标题' \
  --bilibili-category '按本期内容填写页面分区' \
  --youtube-audience not_made_for_kids \
  --youtube-visibility private --json
```

YouTube 受众请按事实选择 `made_for_kids` 或 `not_made_for_kids`，上面的值仅为命令示例。B站分区不能机械照抄。尚不确定时可以先省略这两个选项，计划会保留待确认项，封存时会要求补全。

只做部分平台时重复使用 `--platform`，如 `--platform douyin --platform bilibili`。用户已明确声明原创时增加 `--original`；AI 内容事实明确时增加 `--ai-content yes` 或 `no`，未知则保持默认 `unspecified`。YouTube 默认私享，公开范围必须先向用户展示。

命令返回计划与预览路径，文件在 `.publisher-runs/<任务编号>/`。先阅读完整字幕和预览，必要时编辑 `publish_plan.json` 的 `platform_metadata`。不要改素材清单和运行指纹；换视频、字幕或封面应重新生成任务。

## 检查后封存

实际检查文案和三张封面后：

```bash
publisherctl seal --plan '<publish_plan.json绝对路径>' \
  --content-reviewed --covers-reviewed --json
publisherctl verify --plan '<publish_plan.json绝对路径>' --json
```

`--content-reviewed` 和 `--covers-reviewed` 是对已经完成检查的记录。字幕实际覆盖低于配置阈值时，还要提供 `--subtitle-note '已核对，空白区间为无口播画面……'`。不要为跳过检查填写虚假说明。覆盖率只是辅助指标，不能证明字幕语义与视频完全一致。

只有 `verify` 返回 `ready_for_review`，才表示这份本地计划可交给人工确认。变更计划内容、素材或规则后，旧确认会失效。程序生成的草稿不会自动封存。

## 浏览器人工审核

使用 Codex 时，项目技能位于 [.agents/skills/self-media-publisher/SKILL.md](.agents/skills/self-media-publisher/SKILL.md)。其他 AI 工具也可读取 [AGENTS.md](AGENTS.md) 和 [审核约定](.agents/skills/self-media-publisher/references/runtime-contract.md)。

向用户展示计划、封面和平台范围，收到当前 `review_approval_phrase` 对应的明确确认后：

```bash
publisherctl review-start --plan '<计划>' --approval '确认启动 Ego 审核 <本轮12位指纹>' --json
```

此命令保存确认并冻结本轮计划，不启动或操控浏览器。AI 通过已安装的 ego-browser 技能检查空间冲突、创建各平台独立空间、上传填表，再使用 `review-bind` 和 `review-record` 记录原空间与实际读回。完整命令及证据要求见审核约定。

登录、验证码、旧草稿、风控、原创协议、AI 或版权声明交给用户处理。YouTube Shorts 的封面能力以当前 Studio 实际支持为准，不支持时留作人工事项。

```bash
publisherctl review-status --plan '<计划>' --json
```

| 状态 | 含义 |
|---|---|
| draft | 本地草稿，尚不能启动审核 |
| ready_for_review | 本地计划检查通过，等待明确确认 |
| review_ready | 操作者报告上传、填表、读回和原空间交接已完成 |
| manual_required / blocked / failed | 需要人工处理、被阻止或有明确失败证据 |
| manual_review_finished | 用户明确确认已人工提交，尚不等于系统独立验证公开上线 |

CLI 校验操作者提交的页面证据，不直接读取浏览器。上传、填表、人工提交和平台上线是不同阶段，不能相互替代。

## 本机配置与 Hermes 兼容

公开默认配置在 `config/adapter.json`，示例在 `config/adapter.example.json`。私人覆盖写入 `config/adapter.local.json`（已忽略）。例如主动启用只读规则参考：

```json
{
  "mode": "hermes_read_only",
  "hermes_profile_dir": "~/your-hermes-profile"
}
```

只读取该位置的 SOUL 和相关发布 Skill 指纹，不读取账号配置、不启动 Hermes，也不会改写其文件。默认 `standalone` 不访问该目录。旧适配层 1.x 计划不能直接恢复审核，应使用原始素材重新生成。

默认运行根目录为当前目录。安装包在其他目录使用时，可在子命令前指定 `publisherctl --project-root '<项目目录>' doctor --json`。所有运行产物固定在该项目的 `.publisher-runs`。

## 开发、测试与分享

```bash
python3 -B -m unittest discover -s tests -v
python3 scripts/check_public_files.py
python3 scripts/check_public_files.py --archive .publisher-runs/releases/source.zip
```

测试使用合成素材，不登录账号或提交平台。需要 ffmpeg 才能执行集成测试；缺少时相关测试会显示 skipped，不能算完整通过。

分享使用 Git 仓库或白名单导出的压缩包。不要直接压缩整个工作目录，其中可能有私人运行数据。检查器会拒绝未知待公开路径、符号链接和部分凭据特征，但有限模式检查不能保证发现所有敏感信息，推送前仍要查看待提交文件。

代码结构：`src/self_media_publisher/` 内分别维护配置、规则版本、媒体、平台校验、计划存储、审核记录和命令入口。第三方与迁移说明见 [THIRD_PARTY.md](THIRD_PARTY.md)；迭代记录见 [CHANGELOG.md](CHANGELOG.md)。本项目采用 MIT 许可证。
