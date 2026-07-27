param([string]$InternalKey='change-internal-key')
$headers = @{'X-Internal-Api-Key'=$InternalKey;'Content-Type'='application/json'}
$items = @(
  @{source='OpenAI News';title='OpenAI 发布新的 AI 工具演示';url='https://example.com/openai-tool';summary='官方介绍了面向生产力的新工具。'},
  @{source='GitHub';title='热门开源 Agent 项目发布新版本';url='https://example.com/agent-release';summary='项目增加任务编排和本地部署能力。'},
  @{source='arXiv AI';title='研究团队公开多模态实战方法';url='https://example.com/multimodal-paper';summary='论文讨论多模态模型的工程应用。'}
)
foreach($item in $items){ Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/items/ingest' -Headers $headers -Body ($item|ConvertTo-Json) }
Write-Host '演示资讯已写入。可在 API 文档中分析事件并生成文章。'

