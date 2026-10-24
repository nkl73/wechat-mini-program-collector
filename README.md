# WeChat Mini Program Collector

自用的 Windows 微信小程序内容采集工具。用户打开小程序，Agent 校准页面，脚本完成重复采集。

## 功能

- 截图、本地 OCR、列表滚动和字段提取。
- 校准后进入栏目、逐条读取详情、展开内容并返回。
- 识别已校准的提示弹窗，定位关闭按钮，关闭后核对页面。
- 暂停、停止、断点续跑、去重和来源截图留存。
- 输出可搜索的 HTML 结果页，以及 CSV、JSON、Markdown。
- 正常循环不调用大模型；首次适配和异常由 Agent 判断。

## 使用

需要 Windows、Python 3.10+ 和电脑版微信。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools/requirements.txt
```

打开要采集的小程序页面，让 WorkBuddy 或其他能执行本地脚本、查看图片的 Agent 读取 `skills/wechat-collect/SKILL.md`，告诉它采集范围和字段。先跑小样本，再批量采集。

也可以双击 `start.cmd` 打开本地控制台。控制台遇到未知页面会暂停，不会自行唤醒 Agent。任务数据保存在 `collector-data/`。

## 说明

已完成一轮本机采样。不同小程序需要校准规则，不保证开箱即用或采集完整。采集占用前台窗口，失焦会停止；不自动执行支付、关注、绑定或提交。OCR 可能出错，可对照来源截图核验。

`tools/profiles/` 是现有配置，`examples/navigation-profile.json` 是模拟页面示例。个人截图、账号信息、缓存和采集结果不包含在本仓库中。

```powershell
python -m unittest discover -s tests -v
```
