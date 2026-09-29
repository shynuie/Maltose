# Document Knowledge Base 開發計畫

> 本文件是 Document Knowledge Base（KDB）的主要開發規格與進度追蹤文件。後續 KDB 的開發、驗證與進度更新，都應以本文件為基準。

## 1. 文件狀態

- 整體狀態：`in_progress`
- 目前階段：Phase 6 - Watcher & Operational Improvements
- 原始需求：[plan_doc_knowledge.md](../../plan_doc_knowledge.md)
- 最後更新：2026-09-29

狀態定義：`planned` 尚未開始；`in_progress` 開發中；`blocked` 受到外部條件阻擋；`done` 已完成並驗證；`deferred` 刻意延後。

每次完成工作項目後，必須同步更新 checkbox、目前進度、驗證結果；若架構決策改變，補充決策紀錄。

## 2. 目標

在現有 MyAgent 中建立獨立的 Document Knowledge Base，讓 Agent 能夠：

1. 掃描 configurable document root。
2. 支援 PDF、TXT、Markdown，並預留 DOCX 擴充能力。
3. 偵測新增、修改與刪除的文件。
4. 建立 document-level 與 chunk-level semantic index。
5. 先找候選文件，再在文件內找相關位置。
6. 根據索引位置重新讀取原始文件內容。
7. 透過 Agent tools 交給 TaskBrain 使用。
8. 與現有 Memory 系統保持資料與責任邊界隔離。

核心原則：

> SQL / vector store 是 index；原始文件系統是 Source of Truth。

Summary、embedding 與 cached chunk 只負責定位；需要精確回答時，必須回到原始文件。

## 3. 非目標

- 不重構或合併既有 Memory 系統。
- 不讓 Brain 直接操作 SQL、LanceDB 或 filesystem。
- 不以 vector index 取代原始文件。
- 第一版不拆成遠端微服務或 HTTP service。
- 第一版不處理 OCR、圖片理解與複雜表格還原。
- 第一版不要求 OpenClawBrain 支援本地 KDB tool loop。

## 4. 現有專案整合邊界

目前可重用：

- `TaskBrain`：本地模型 orchestration 與 tool-call loop。
- `ToolRegistry`：註冊與執行 Agent tools。
- `CapabilityAdapter`：將外部能力暴露成 tools。
- `QwenEmbeddingProvider`：現有 embedding provider。
- LanceDB：現有 Memory 的向量儲存選項。
- TOML config 與 `myagent.agent.cli`。

整合原則：

- KDB 優先整合 `TaskBrain`。
- KDB 不修改 Memory 的資料模型與 repository。
- 可以重用 embedding provider 的介面與模型，但索引資料必須獨立。
- KDB tool handler 只依賴 `DocumentKnowledgeService`。
- Parser、indexer、retrieval service 不依賴 TaskBrain。

## 5. 目標架構

```text
Document Root
    -> Document Scanner
    -> Parser Registry
    -> Summary Service / Chunking Service
    -> Summary Embedding / Chunk Embedding
    -> KDB Metadata + Vector Storage
    -> Document Knowledge Service
    -> TaskBrain Tools
```

第一版是同一個 Python process 內的獨立 service/module；清楚的介面要保留未來拆成 background worker 或 API service 的能力。

目標目錄：

```text
myagent/knowledge/
├── __init__.py
├── models.py
├── config.py
├── scanner.py
├── chunker.py
├── summarizer.py
├── embeddings.py
├── indexer.py
├── retrieval.py
├── source_reader.py
├── tools.py
├── parsers/
│   ├── base.py
│   ├── text.py
│   ├── markdown.py
│   ├── pdf.py
│   └── docx.py
    └── repositories/
        ├── base.py
        ├── metadata.py
        └── vector.py
```

### 5.1 原始文件目錄規劃

`documents_root` 預設使用 repo 底下的 `documents/`，但必須保持 configurable：

```text
documents/
├── inbox/       # 尚未整理、剛匯入的文件
├── personal/    # 個人資料、生活、健康、財務
├── work/        # 工作相關文件
├── projects/    # 長期專案資料
├── papers/      # 論文、研究資料、技術文章
├── notes/       # 使用者或 Agent 產生的筆記
└── archive/     # 已不常使用但仍需保留
```

目錄的主要目的不是語意檢索，而是：

- 方便使用者人工瀏覽與管理。
- 提供基本的權限與敏感度邊界。
- 表達文件生命週期，例如 `inbox` 與 `archive`。
- 提供穩定的粗粒度 collection，例如 `work`、`projects`、`papers`。

不應建立過深的主題目錄，例如 `work/company/team/project/year/topic/type/`。主題、專案與 tags 應保存於 metadata，由 DB search 與 semantic retrieval 處理。

如果 Agent 無法判斷文件分類，預設放入 `inbox/`，再由後續整理流程分類；不應為了分類失敗而中止文件保存。

## 6. Service 邊界

### DocumentScanner

遞迴掃描 root、過濾副檔名、計算 SHA-256，辨識新增、修改、刪除與未變更文件。

```python
class DocumentScanner:
    def scan(self, root: Path) -> ScanResult:
        ...
```

### DocumentParser

將不同格式轉成統一的 `ParsedDocument`，並保留 page、section、offset 等定位資訊。初期實作 TXT、Markdown、PDF；DOCX 後續加入。

### ChunkingService

只處理 `ParsedDocument`，產生包含 `chunk_index`、`page`、`section`、`start_offset`、`end_offset` 的 chunks。不得依賴 database。

### SummaryService

產生 document-level summary，與 embedding provider 解耦，並提供 deterministic fallback 供測試與離線模式使用。

### EmbeddingProvider

```python
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...
```

Provider 不應知道文件 metadata 或 repository。

### DocumentIndexer

串接 scanner、parser、summarizer、chunker、embedding 與 repository，執行完整 indexing、skip unchanged，以及刪除 cleanup。更新應具備一致性：新 index 完成後才替換舊 index。

### SourceReader

根據 document ID 取得原始 path，驗證 path 位於 document root 之下，並從原始檔案讀取全文或指定 page/section/offset。

### DocumentKnowledgeService

對 Agent 暴露唯一 domain service：

```python
class DocumentKnowledgeService:
    def search_documents(self, query: str, top_k: int = 5): ...
    def search_in_document(self, document_id: str, query: str, top_k: int = 10): ...
    def read_document(self, document_id: str, location=None): ...
```

## 7. 資料模型與儲存

### Document metadata

```text
documents
---------
id, path, filename, title, file_type, summary,
content_hash, file_size, created_at, modified_at,
indexed_at, status, collection, metadata_json
```

metadata 應能保存下列可篩選欄位或等價資訊：

- `collection`：例如 `personal`、`work`、`projects`、`papers`、`notes`。
- `project`：所屬專案。
- `tags`：主題與用途標籤。
- `source`：`user_imported`、`agent_created` 或 `folder_scan`。
- `sensitivity`：例如 `private`、`work`。
- `language`：文件主要語言。
- `imported_at`：匯入時間。

目錄分類保持淺層；metadata、tags 與 semantic search 負責細粒度知識分類。

### Chunk index

```text
document_chunks
---------------
id, document_id, chunk_index, page, section,
start_offset, end_offset, text_preview, embedding, metadata_json
```

`text_preview` 只作 retrieval preview 或 debug，不能取代原始文件。

建議使用獨立 KDB storage：

```text
data/
├── memory.lancedb
└── knowledge/
    ├── metadata.sqlite3
    └── vectors.lancedb
```

KDB 不可寫入既有 Memory table，也不可共用 Memory 的 document schema。

### 文件移動與 hash

文件移動不應被視為新文件。若新舊檔案的 `content_hash` 相同，應保留原有 `document_id`、summary、chunks 與 embeddings，只更新 `path`、collection 或相關 metadata。只有內容 hash 改變時，才重新執行 parse、summary、chunk 與 embedding。

## 8. Retrieval 流程

文件級查詢：

```text
query -> query embedding -> document.summary_embedding search -> Top-K documents
```

文件內容查詢：

```text
query
-> document-level retrieval
-> candidate document IDs
-> chunk search within candidates
-> location
-> SourceReader 讀取原始文件
-> source content 給 TaskBrain
```

Brain 不得直接搜尋全部 chunks，也不得自行組合 SQL 或 vector query。

## 9. 文件匯入與 Agent 建檔

所有新增文件都必須先成為 document root 下的原始文件，再進入 indexing pipeline；不可直接把文字或 embedding 寫入 vector store。

### 9.1 使用者放入文件

```text
使用者把文件放入 documents/
    -> scanner 偵測新文件
    -> indexing pipeline
    -> 建立 KDB index
```

### 9.2 匯入外部文件

使用者要求匯入外部文件時，系統應透過 `DocumentIngestionService` 驗證來源並複製到 managed document root，而不是直接保存外部 path 或 symlink：

```text
驗證 source path
    -> 驗證 destination 不逃出 document root
    -> 複製到 documents/<collection>/
    -> 計算 hash
    -> 執行 indexing
```

預設採複製而非 symlink，避免外部檔案被移動或刪除後造成 source 不穩定。

### 9.3 Agent 產生文件

Agent 可以建立 Markdown/TXT 文件，但必須透過受限 service：

```python
class DocumentIngestionService:
    def import_file(self, source_path: Path, destination: str): ...
    def create_document(
        self,
        content: str,
        filename: str,
        directory: str = "notes",
        file_type: str = "markdown",
    ): ...
```

Agent 未指定分類時，文件放入 `documents/inbox/`；已明確指定筆記時，可放入 `documents/notes/`。建立成功後仍必須完成 indexing，才能回報文件已加入知識庫。

### 9.4 Agent tools

第一版可提供：

- `import_document(source_path, destination)`：將外部文件複製到 managed document root。
- `create_document(filename, directory, content)`：建立 Agent 產生的文件。

兩者都必須共用同一條流程：

```text
write/copy source file
    -> calculate hash
    -> parse
    -> summarize
    -> chunk
    -> embed
    -> persist index
```

### 9.5 新增文件安全規則

- 只能寫入 configurable document root。
- 阻擋 `../`、絕對路徑逃逸與 symlink traversal。
- 預設禁止覆蓋既有文件；覆蓋需要明確確認。
- 來源不存在時不得建立假的 index。
- 寫檔成功但 indexing 失敗時，保留原始文件並標記 `indexing_failed`。
- 文件過大時應套用大小限制。
- Agent 不應自行修改敏感度或權限設定。

### 9.6 Indexing 狀態

```text
created -> pending_index -> indexing -> indexed
                              └──────> failed
```

若未來改成背景 indexing，tool 可先回傳 `pending_index`，不得宣稱已完成索引。

## 10. Agent Tools

第一版提供：

### `search_documents`

找出可能相關的文件，至少回傳 `document_id`、`title`、`path`、`summary`、`similarity_score`、`metadata`。

### `search_in_document`

在指定文件內找 chunks/location，至少回傳 `document_id`、`chunk_id`、`page`、`section`、offset、`similarity_score`，可附 preview。

### `read_document`

從原始 filesystem 讀取全文或指定位置。

TaskBrain instruction 必須要求：先 search，再在需要精確回答時呼叫 `read_document`；只拿到 summary 或 preview 時不得假裝已取得完整來源。

## 11. 設定與 CLI

建議增加：

```toml
[knowledge]
enabled = true
documents_root = "documents"
metadata = "data/knowledge/metadata.sqlite3"
vectors = "data/knowledge/vectors.lancedb"
supported_extensions = [".pdf", ".txt", ".md"]
embedding = "qwen3-embedding-0.6b"
embedding_device = "cpu"
chunk_size = 1200
chunk_overlap = 150
summary_enabled = true
watch = false
```

第一版 CLI：

```bash
myagent documents index
myagent documents list
myagent documents search "我的碩士論文"
```

後續 CLI：

```bash
myagent documents index --path documents/work/report.pdf
myagent documents inspect <document-id>
myagent documents remove <document-id>
```

## 12. 分階段開發計畫

### Phase 0 - Architecture & Boundary

狀態：`in_progress`

- [x] 閱讀並整理 KDB 需求。
- [x] 確認 KDB 與 Memory 責任邊界。
- [x] 確認第一版採 in-process service。
- [x] 確認 TaskBrain 為第一個整合點。
- [x] 建立本開發計畫文件。
- [x] 確認 metadata storage 與 vector storage 的最終選型：SQLite metadata、LanceDB vectors。
- [x] 確認第一版 summary provider：extractive summary fallback。

完成條件：service 邊界、storage 隔離與第一版工作拆分確定。

### Phase 1 - Domain Models & Parser Foundation

狀態：`done`

- [x] 建立 `myagent/knowledge/` package。
- [x] 建立 document/chunk/location/parsed document models。
- [x] 建立 parser abstraction 與 registry。
- [x] 實作 TXT parser。
- [x] 實作 Markdown parser。
- [x] 實作 format-neutral chunker。
- [x] 建立 parser 與 location 單元測試。

完成條件：TXT/Markdown 可轉成統一 representation，chunker 不需要知道格式。

### Phase 2 - Metadata Storage & Scanner

狀態：`done`

- [x] 建立 SQLite metadata repository。
- [x] 實作 recursive scanner 與 SHA-256。
- [x] 實作基本 supported-extension filtering。
- [x] 建立 metadata repository interface。
- [x] 實作 configurable document root。
- [x] 實作新增、未變更、修改判斷。
- [x] 實作刪除 cleanup / soft-delete。
- [x] 定義 `documents/inbox/`、`personal/`、`work/`、`projects/`、`papers/`、`notes/`、`archive/` 的初始分類。
- [x] 實作 path 移動但 content hash 不變時只更新 metadata/path。
- [x] 加入 storage 初始化流程。

完成條件：未變更文件正確 skip，刪除文件不會留下可檢索 orphan。

### Phase 3 - Chunking, Embedding & Indexing

狀態：`done`

- [x] 實作 chunking service。
- [x] 抽出共用 embedding provider interface。
- [x] adapter 化既有 Qwen embedding provider。
- [x] 建立 document summary embedding index repository。
- [x] 建立 chunk embedding index repository。
- [x] 實作 DocumentIndexer orchestration 與 vector replacement contract。
- [x] 加入 PDF parser。
- [x] 建立 document/chunk retrieval tests。

完成條件：新文件可完成 parse → summary → chunk → embedding → persist，修改後不混用舊 chunks。

### Phase 4 - Source Reader & Retrieval Service

狀態：`done`

- [x] 實作 SourceReader。
- [x] 實作 TXT/Markdown offset read。
- [x] 實作 PDF parser 與 page read（需要 optional `pypdf` dependency）。
- [x] 實作 path traversal 防護。
- [x] 實作 hierarchical retrieval。
- [x] 處理 source 不存在與 location 失效。
- [x] 加入 source-of-truth integration tests。

完成條件：retrieval 結果可以回到原始檔案，且 document root 外的 path 無法讀取。

### Phase 5 - TaskBrain Integration

狀態：`done`

- [x] 實作 DocumentIngestionService。
- [x] 加入 `import_document` tool。
- [x] 加入 `create_document` tool。
- [x] 加入 document root、overwrite 與 indexing status 驗證。
- [x] 建立 DocumentKnowledgeService。
- [x] 建立 KDB tool adapter。
- [x] 定義三個 KDB tools。
- [x] 更新 TaskBrain system instruction。
- [x] 接入主程式的 KDB config 與 TaskBrain bootstrap。
- [x] 接入 TOML config 與 `myagent-documents` CLI。
- [x] 驗證 Memory tools 與 KDB tools 可同時註冊。
- [x] 建立 fake model tool-call integration tests。

完成條件：TaskBrain 可完成 search → read，且不直接知道 KDB storage implementation。

### Phase 6 - Watcher & Operational Improvements

狀態：`in_progress`

- [x] 加入 file watcher abstraction（先以 polling implementation 提供可替換事件模型）。
- [x] 定義 background indexing queue 的 job、狀態、retry 與錯誤記錄契約。
- [x] 加入 in-process background indexing worker 與 queue job 消費流程。
- [x] 將 watcher event 映射到 queue，並處理 delete/move 的 metadata 更新。
- [x] 建立 `KnowledgeRuntime`，串接 watcher、dispatcher、queue 與 worker lifecycle。
- [x] 接入 `myagent-documents watch` CLI 與 polling/retry runtime options。
- [x] 將 `./start` 整合為同時啟動 Agent 與 watcher，並在退出時統一 shutdown。
- [x] 加入 `myagent-documents repair`，修復 `indexing_failed` 與 `pending_index` 文件。
- [x] 加入 orphan vector detection 與明確的 `--prune-orphans` cleanup option。
- [x] 加入 SQLite durable indexing queue，保存 job state 並恢復中斷工作。
- [x] 加入 `myagent-documents queue` 狀態查詢與 status filter。
- [x] 將 watcher 空輪詢降為 DEBUG，並將 `./start` 的 KDB log 分離到 `data/logs/knowledge.log`。
- [x] 加入 scanner、change detection、indexing 與 CLI progress logging。
- [ ] 加入 embedding batch processing。
- [x] 加入 reindex / repair command。
- [ ] 評估是否拆成獨立 background service。

完成條件：文件異動可自動觸發 indexing，失敗不破壞既有可用 index。

## 13. 驗收標準

### 功能

- [x] 可設定 document root。
- [x] 可索引 TXT、Markdown、PDF。
- [x] 可搜尋文件級 summary。
- [x] 可在指定文件內搜尋 chunks。
- [x] 可讀取原始文件全文或指定位置。
- [x] hash 未變更時不重複 indexing。
- [x] 修改後會重建相關 index。
- [x] 刪除後不會出現 orphan retrieval result。
- [x] 外部文件可被複製到 managed document root 後完成 indexing。
- [x] Agent 可建立文件並完成 indexing。
- [x] 未指定分類的文件會進入 `inbox/`。
- [x] 移動相同 hash 的文件不會重新建立 embedding。

### 架構

- [x] KDB 與 Memory 使用不同 storage/domain model。
- [x] Brain 不直接操作 storage implementation。
- [x] Parser 不依賴 retrieval service。
- [x] Embedding provider 可替換。
- [x] retrieval result 帶有可定位的 document/location 資訊。

### 安全與可靠性

- [x] path traversal 被阻擋。
- [x] document root 外檔案不可被讀取。
- [x] 原始文件不存在時回傳明確錯誤。
- [ ] index 部分失敗時不破壞上一版 index。
- [x] 空結果時 Brain 不編造文件內容。
- [x] Agent 不可寫入 document root 之外的路徑。
- [x] indexing 失敗時原始文件仍被保留並標記失敗狀態。

## 14. 測試策略

### Unit tests

Parser、chunk boundary、hash、scanner change detection、repository CRUD、embedding adapter、source location validation。

### Integration tests

完整 indexing pipeline、document-level retrieval、document-scoped chunk retrieval、source read-back、修改 reindex、刪除 cleanup。

### Agent integration tests

TaskBrain tool-call round-trip、KDB 與 Memory tools 同時存在、空結果時不編造內容。

測試優先使用 temporary document root 與 fake embedding/summarizer，避免單元測試依賴大型模型或外部 API。

## 15. 決策紀錄

### ADR-001：KDB 與 Memory 分離

KDB 不與 Memory 共用 domain table；storage path 與 repository 分離。原因是兩者生命週期、資料來源、查詢語意與安全邊界不同。

### ADR-002：第一版採 in-process service

第一版在 MyAgent process 內使用獨立 service interfaces，不立即拆微服務，以降低部署與除錯成本，並保留未來拆分彈性。

### ADR-003：原始文件是 Source of Truth

summary、embedding 與 chunk cache 只用於定位；精確回答前必須能回到原始文件。

### ADR-004：優先整合 TaskBrain

第一版 KDB tools 接入 TaskBrain，因為 TaskBrain 已有本地 ToolRegistry 與 tool-call loop；OpenClawBrain 目前是直接 Chat Completions 呼叫。

### ADR-005：目錄保持淺層，語意分類交給 metadata

`documents/` 以 `inbox`、`personal`、`work`、`projects`、`papers`、`notes`、`archive` 作為初始粗粒度分類。目錄用於人工管理、生命週期與基本權限；project、tags、topic 等細粒度分類由 metadata 與 semantic search 處理。

### ADR-006：新增文件必須先落地成原始 source

使用者或 Agent 新增文件時，必須先寫入或複製到 managed document root，再執行 indexing。不可直接將內容或 embedding 寫入 KDB vector store；這樣才能維持原始文件是 Source of Truth。

## 16. 目前進度

### 已完成

- 已閱讀 KDB 需求文件。
- 已檢查現有 TaskBrain、Capability、Memory、Embedding、CLI 與 config 架構。
- 已確定 KDB 不修改既有 Memory 設計。
- 已建立本開發計畫文件。
- 已完成 KDB 核心 domain model、parser、scanner、change detection、metadata repository 與 vector repository。
- 已完成 TXT、Markdown、PDF 的 parsing、chunking、summary 與 indexing pipeline。
- 已完成 source-of-truth reader 與 document/chunk 階層式 retrieval。
- 已完成 Agent tools、TaskBrain bootstrap、TOML config 與 `myagent-documents` CLI 整合。
- 已加入 lazy embedding loading、force reindex、indexing progress logging 與錯誤狀態保存。
- 已完成 Agent 對話 session、speech interrupt 與 KDB/Memory 共存的整合驗證。

### 目前進行中

- Phase 6：補齊 reindex/repair、batch processing 與 crash recovery。

### 下一步

1. 加入 reindex / repair command，支援失敗文件與孤立 index 的修復。
2. 評估 embedding batch processing。
3. 評估 process crash recovery，以及是否需要 durable queue。
4. 再決定 watcher 與 queue 是否拆成獨立 background service。

### 2026-09-29 Progress Update

- 狀態：`in_progress`
- 完成：
  - [x] 同步 Phase 0–5 的實際完成狀態。
  - [x] KDB 測試套件 45 項通過。
  - [x] 建立 `DocumentWatcher` contract、watch event model 與 polling watcher。
  - [x] 覆蓋 create、modify、delete、move 與 watcher lifecycle 測試。
  - [x] 建立 `IndexingQueue` contract 與 thread-safe in-memory queue。
  - [x] 定義 queued、running、succeeded、failed 狀態與 bounded retry 行為。
  - [x] 建立可同步 drain、可停止 background thread 的 `IndexingWorker`。
  - [x] 驗證 worker 的成功、retry、永久失敗與停止流程。
  - [x] 建立 watcher event dispatcher，串接 create/modify、move、delete lifecycle。
  - [x] delete 時同步 soft-delete metadata 並移除 document vectors。
  - [x] 驗證手動 polling cycle 與 background runtime 自動 indexing。
  - [x] 接入 `myagent-documents watch`、poll interval 與 max retry options。
  - [x] `watch` 使用 lazy embedding，避免啟動時無條件載入模型。
  - [x] 更新 `./start` 使用完整 KDB/voice extras，避免啟動時清除 vector-memory 依賴。
  - [x] 加入 repair planner 與 CLI no-work path；無待修復文件時不載入 embedding。
  - [x] 加入 orphan vector detection 與選擇性 pruning。
  - [x] 將 `watch` runtime 改用 SQLite durable queue，支援 process restart recovery。
  - [x] 提供 queued/running/succeeded/failed job 的 CLI 可觀測性。
  - [x] 降低 watcher 空輪詢的 INFO log noise，避免每秒輸出影響主 Agent 可觀測性。
- 進行中：
  - [ ] Phase 6 operational improvements。
- 驗證：`uv run python -m unittest discover -s tests -p 'test_knowledge*.py'`
- 結果：51 tests passed；`bash -n start` 通過。
- 阻塞：無。
- 下一步：評估 queue 的 stale job policy、並行 worker 數量與是否拆成獨立 background service。

## 17. 進度更新格式

```markdown
### YYYY-MM-DD Progress Update

- 狀態：`in_progress` / `done` / `blocked`
- 完成：
  - [x] ...
- 進行中：
  - [ ] ...
- 驗證：`uv run pytest ...`
- 結果：...
- 阻塞：無 / 說明原因
- 下一步：...
```

任何實作若偏離本文件的架構或 Source of Truth 原則，必須先在「決策紀錄」補充原因，再進行後續開發。
