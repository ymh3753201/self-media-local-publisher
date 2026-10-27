---
name: self-media-publisher
description: 使用本项目为视频和字幕生成五平台差异化发布计划、检查统一封面，并在明确确认后用 Ego 上传填表、读回和人工交接。最终发布默认由用户完成。
---

# 独立本地自媒体发布助手

从项目根目录运行命令；安装后也可使用 `publisherctl`。本项目默认不依赖 Hermes、publisher-agent 或 social-auto-upload。

## 任务准备

读取根目录 AGENTS.md、运行 `doctor --json` 和 `context --json`。可选 `hermes_read_only` 模式下，根据 context 的 `hermes_context.files` 现场只读对应规则；不启动 Hermes。

必须提供匹配的视频和 SRT。先 `inspect --video <文件> --subtitle <文件> --json`，阅读完整字幕，核对实际覆盖率和空白间隔。所有文案以字幕事实为依据，默认生成的摘录仅是草稿。

需要生成或补齐封面时，读取 [封面规范](references/cover-policy.md)。在 Codex 加载内置 imagegen Skill，调用 image_gen；三比例共享主视觉和标题，保存到运行目录并实际视觉检查。

## 生成、核对和封存

```bash
python3 scripts/publisherctl.py plan \
  --video <视频> --subtitle <字幕> \
  --cover <封面1> --cover <封面2> --cover <封面3> \
  --cover-title <统一标题> \
  --bilibili-category <本期分区> \
  --youtube-audience <made_for_kids或not_made_for_kids> --json
```

只有用户明确声明原创才加 `--original`；`--ai-content yes/no` 同样必须有事实依据，未知保持 `unspecified`。不推断 YouTube 受众，不把所有 B站视频设为 AI 分区。

读取返回的计划和预览，按完整字幕优化各平台标题、简介和话题，检查三张封面逐字一致、主体与裁切合格。修改计划后运行：

```bash
python3 scripts/publisherctl.py seal --plan <计划> --content-reviewed --covers-reviewed --json
python3 scripts/publisherctl.py verify --plan <计划> --json
```

这两个 reviewed 参数表示检查已经实际完成，不是绕过检查的开关。字幕实际覆盖不足时，核对空白部分并使用 `--subtitle-note <核对说明>`；不能替缺失字幕补造事实。

仅 `ready_for_review` 才可展示给用户；同时展示封面、各平台文案、分区、受众、声明和可见性。等待用户明确确认该计划的 `review_approval_phrase` 后，执行 `review-start --plan <计划> --approval <原确认语句>`。

## 浏览器审核与结果

读取 [运行、审核和证据约定](references/runtime-contract.md)。检查 `doctor --browser`，加载当前环境的 ego-browser 技能；CLI 没有内置自动上传器。

列出并检查空间冲突后，为各平台创建独立 `codex-publisher:<run-id>:<platform>` 空间并用 `review-bind` 保存。遵循 snapshot → 操作 → 页面读回；不接管其他空间。出现登录、风控、声明、旧草稿或版权检查时，交接原空间并记录 `manual_required`。

字段、视频和封面都完成且原空间交给用户后，才通过 `review-record` 保存 `review_ready`。不点击最终发布或草稿保存。用户后续明确确认人工完成后才记录 `manual_review_finished`。使用 `review-status` 查看原任务；不要为已完成平台重新上传。
