from pathlib import Path
import zipfile

from PIL import Image

from app.config import settings
from app.database import SessionLocal
from app.models import Article, ArticleStatus, EventCluster, FeedItem, Source
from app.publication import generate_wechat_publication


def test_generate_wechat_publication(reset_db, tmp_path):
    original_export_dir = settings.export_dir
    settings.export_dir = tmp_path
    try:
        with SessionLocal() as db:
            source = Source(name="测试官方源", kind="rss", url="https://example.com/feed", official=True)
            db.add(source)
            db.flush()
            event = EventCluster(canonical_title="测试事件", topic="AI 工具", score=9)
            db.add(event)
            db.flush()
            item = FeedItem(
                source_id=source.id,
                title="官方测试消息",
                url="https://example.com/news",
                normalized_url="https://example.com/news",
                event_id=event.id,
            )
            db.add(item)
            db.flush()
            event.primary_item_id = item.id
            article = Article(
                event_id=event.id,
                title="一篇用于验证公众号成品生成的文章",
                status=ArticleStatus.approved,
                content={
                    "lead": "这是经过人工批准的导语。",
                    "facts": ["事实一", "事实二"],
                    "analysis": "这项变化值得关注。",
                    "user_impact": ["用户影响一"],
                    "developer_notes": ["开发者关注一"],
                    "actions": ["发布前再次核验来源。"],
                },
            )
            db.add(article)
            db.commit()
            db.refresh(article)

            manifest = generate_wechat_publication(db, article)

        output_dir = tmp_path / Path(manifest["preview_url"].removeprefix("/generated/")).parent
        markdown = (output_dir / "article.md").read_text(encoding="utf-8")
        html = (output_dir / "preview.html").read_text(encoding="utf-8")
        assert markdown.count("\n# ") == 0
        assert markdown.startswith("# 一篇用于验证")
        assert "## 写在最后" in markdown
        assert "images/01-section.jpg" in markdown
        assert 'src="images/01-section.jpg"' in html
        assert "https://example.com/news" in html
        assert "<script" not in (output_dir / "cover.svg").read_text(encoding="utf-8").lower()
        with Image.open(output_dir / "cover.jpg") as cover:
            assert cover.size == (1800, 766)
        with Image.open(output_dir / "images" / "01-section.jpg") as illustration:
            assert illustration.size == (1200, 500)
        assert "Noto Sans CJK SC" in (output_dir / "cover.svg").read_text(encoding="utf-8")
        bundle_path = output_dir / "公众号完整素材包.zip"
        assert bundle_path.exists()
        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
            assert {"article.md", "preview.html", "cover.jpg", "cover.svg", "images/01-section.jpg"} <= names
    finally:
        settings.export_dir = original_export_dir
