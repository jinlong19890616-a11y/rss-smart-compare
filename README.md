# RSS 智能补集对比版

这是独立测试插件，不修改下载机现有 `RssSubscribe`。

## 目录

- `rsssubscribe_smart/__init__.py`：独立插件副本，插件类名 `RssSubscribeSmart`
- `rsssubscribe_smart/smart_guard.py`：库集数、已下载任务、已整理文件的判重逻辑
- `rsssubscribe_smart/dryrun_compare.py`：离线 dry-run，不访问网络、不连接 qBittorrent、不下载
- `rsssubscribe_smart/file_selection_plan.py`：根据种子文件列表生成 priority 选择计划，不实际操作 qBittorrent
- `rsssubscribe_smart/qbittorrent_adapter.py`：qBittorrent 三步边界适配器；目前只由 FakeQbit 测试，不连接真实服务器
- `tests/`：现有 Guard、dry-run、文件选择计划和模拟 qBittorrent 测试

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

当前只是在 Mac 资料盘完成本地验证，未安装到 OVH 下载机。
