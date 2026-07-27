from app.services import ModelOutputError, normalize_url, parse_model_json, similarity
from app.config import settings
from app.database import SessionLocal
from app.models import Article, ArticleStatus, EventCluster, FeedItem, Source
from app.services import create_cover, export_package, wechat_draft

def test_normalize_url_removes_tracking():
    assert normalize_url('HTTPS://Example.com/a/?utm_source=x&b=2') == 'https://example.com/a?b=2'

def test_title_similarity():
    assert similarity('OpenAI 发布新模型 GPT 6', 'OpenAI GPT 6 新模型发布') > .55
    assert similarity('天气预报', '开源 Agent 工具') < .2

def test_parse_model_json_rejects_empty_output():
    response=type('Response',(),{'output_text':'','output':[],'status':'completed'})()
    try: parse_model_json(response)
    except ModelOutputError as exc: assert '空文本' in str(exc)
    else: raise AssertionError('空模型响应必须被拒绝')

def test_parse_model_json_accepts_object():
    response=type('Response',(),{'output_text':'{"total_score": 8}'})()
    assert parse_model_json(response)=={'total_score':8}

def test_ingest_idempotent(reset_db):
    c=reset_db; h={'X-Internal-Api-Key':'internal'}
    body={'source':'OpenAI News','title':'测试','url':'https://example.com/a?utm_source=x'}
    a=c.post('/api/items/ingest',headers=h,json=body).json(); b=c.post('/api/items/ingest',headers=h,json={**body,'url':'https://example.com/a'}).json()
    assert a['id']==b['id']

def test_auth(reset_db):
    assert reset_db.get('/api/articles').status_code==200
    assert reset_db.get('/api/articles',headers={'X-Admin-Password':'test'}).status_code==200

def test_article_can_be_deleted_without_deleting_source_event(reset_db):
    headers = {'X-Admin-Password': 'test'}
    with SessionLocal() as db:
        event = EventCluster(canonical_title='待删除稿件来源事件', topic='AI工具', score=8)
        db.add(event)
        db.flush()
        article = Article(
            event_id=event.id,
            title='可删除稿件',
            title_options=['可删除稿件'],
            content={'lead': '测试'},
            status=ArticleStatus.pending,
        )
        db.add(article)
        db.commit()
        article_id, event_id = article.id, event.id

    response = reset_db.delete(f'/api/articles/{article_id}', headers=headers)
    assert response.status_code == 200
    assert response.json() == {'ok': True, 'article_id': article_id}
    assert reset_db.get('/api/articles', headers=headers).json() == []
    with SessionLocal() as db:
        assert db.get(EventCluster, event_id) is not None

def test_cover_export_and_mock_wechat(reset_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'asset_dir', tmp_path/'assets')
    monkeypatch.setattr(settings, 'export_dir', tmp_path/'exports')
    monkeypatch.setattr(settings, 'wechat_mode', 'mock')
    with SessionLocal() as db:
        source=Source(name='Official',kind='rss',url='https://example.com/rss',official=True); db.add(source); db.flush()
        event=EventCluster(canonical_title='AI工具发布',topic='AI工具',score=9); db.add(event); db.flush()
        item=FeedItem(source_id=source.id,title='AI工具发布',url='https://example.com/news',normalized_url='https://example.com/news',event_id=event.id); db.add(item)
        article=Article(event_id=event.id,title='AI工具发布：这次有哪些变化',title_options=['AI工具发布：这次有哪些变化'],content={'lead':'导语','facts':['已发布'],'analysis':'有实用价值','actions':['阅读原文']},status=ArticleStatus.approved); db.add(article); db.commit(); db.refresh(article)
        cover=create_cover(db,article); assert (tmp_path/'assets'/f'article-{article.id}-cover.jpg').exists()
        package=export_package(db,article); assert package.exists()
        result=wechat_draft(db,article,'test-key'); assert result['mode']=='mock' and result['success']
        assert wechat_draft(db,article,'test-key')==result
def test_workflows_one_to_three_are_merged(reset_db, monkeypatch):
    monkeypatch.setattr("app.main.collect_all", lambda _db: {"ok": True, "errors": {}, "sources": {}})
    monkeypatch.setattr("app.main._score_today", lambda _db: {
        "date": "2026-07-25", "total_count": 1, "count": 1, "success_count": 1,
        "failure_count": 0, "event_ids": [8],
        "rankings": [{"rank": 1, "event_id": 8, "title": "测试事件", "topic": "AI工具",
                      "score": 9.0, "needs_review": False}],
        "failures": [],
    })
    monkeypatch.setattr("app.main._choose_articles", lambda _db: [12])
    headers = {"X-Admin-Password": "test"}

    response = reset_db.post("/api/workflows/1/run", headers=headers)
    assert response.status_code == 200
    runs = reset_db.get("/api/runs", headers=headers).json()
    assert runs[0]["name"] == "01 资讯到候选稿"
    assert runs[0]["status"] == "success"
    assert runs[0]["details"]["article_ids"] == [12]
    assert runs[0]["details"]["rankings"][0]["score"] == 9.0

    assert reset_db.post("/api/workflows/2/run", headers=headers).status_code == 404
    assert reset_db.post("/api/workflows/3/run", headers=headers).status_code == 404


def test_workflow_settings_include_article_limit(reset_db):
    headers = {"X-Admin-Password": "test"}
    current = reset_db.get("/api/workflows/1/settings", headers=headers).json()
    assert current["article_limit"] == 5
    body = {
        "item_limit": 4,
        "article_limit": 3,
        "sources": [{"id": item["id"], "enabled": item["enabled"], "url": item["url"]} for item in current["sources"]],
    }
    response = reset_db.put("/api/workflows/1/settings", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["item_limit"] == 4
    assert response.json()["article_limit"] == 3
