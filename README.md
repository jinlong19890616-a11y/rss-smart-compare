# RSS 智能补集对比版

这是独立测试插件，不修改下载机现有 `RssSubscribe`。

## 目录

- `rsssubscribe_smart/__init__.py`：独立插件副本，插件类名 `RssSubscribeSmart`
- `rsssubscribe_smart/smart_guard.py`：库集数、已下载任务、已整理文件的判重逻辑
- `rsssubscribe_smart/dryrun_compare.py`：离线 dry-run，不访问网络、不连接 qBittorrent、不下载
- `rsssubscribe_smart/file_selection_plan.py`：根据种子文件列表生成 priority 选择计划，不实际操作 qBittorrent
- `rsssubscribe_smart/qbittorrent_adapter.py`：qBittorrent 三步边界适配器；目前由 FakeQbit 测试
- `plugins.v2/rsssubscribesmart/`：MoviePilot V2 市场安装目录
- `tests/`：现有 Guard、dry-run、文件选择计划和模拟 qBittorrent 测试

## MoviePilot V2 整季包流程

插件版本 0.2.0 起，识别到季号但没有明确集号的电视剧资源时，会从已识别的 TMDB 季集数生成目标集集合，并传入 MoviePilot 原生下载链。MoviePilot 会先暂停 qBittorrent 任务、读取文件列表、按文件名识别集数，将媒体库已有集设为 `priority=0`、缺失集设为 `priority=1`，然后恢复任务。无法取得明确季集数，或文件无法安全识别时，插件继续延后，不提交整季下载。


## dry-run

```bash
python3 rsssubscribe_smart/dryrun_compare.py tests/fixtures/basic.json
```

输入 fixture 的 `library` 是季到集数列表，`rss` 是 RSS 标题。输出会同时展示：

- 现有逻辑倾向；
- 智能逻辑倾向；
- 库中已有集；
- 缺失集；
- 整季包是否需要 qBittorrent 独立视频文件列表。

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前代码已发布到 GitHub，并可通过 MoviePilot V2 插件市场安装；真实 OVH 测试仍需在插件停用状态下先更新，再选择小型测试资源验证。
