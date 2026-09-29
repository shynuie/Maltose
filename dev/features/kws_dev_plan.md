# KWS 優化開發計畫

## 文件狀態

- 狀態：`in_progress`
- 最後更新：2026-09-29
- 目前階段：資料集建立與離線基準測試
- 正式設定：已套用一般距離候選參數，far-field 仍待模型評估

## 目標

提升 wake word「麥芽糖」在實際麥克風、不同距離、音量與背景噪音下的召回率，同時控制誤觸發、延遲與 CPU 成本。

## 非目標

- 第一階段不更換 Sherpa-ONNX KWS 模型。
- 不把更換麥克風、調整硬體 input gain 或限定特定 audio device 當成解法；目標是 device-agnostic software KWS。
- 不在沒有負樣本與離線數據支持前直接降低 production threshold。
- 不把一般 STT 音訊前處理與 wake word 前處理混成同一條 pipeline。
- 不優先追求複雜的神經網路降噪；先完成可測量、可回退的輕量方案。

## 目前基線

### 模型與輸入

- 模型：Sherpa-ONNX Zipformer KWS `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`。
- Sample rate：16kHz。
- Channel：mono。
- Format：16-bit PCM。
- VAD frame：20ms；KWS frame：30ms，已完成解耦。
- threshold：`0.25`。
- `keywords_score`：`1.0`。
- `num_trailing_blanks`：`1`。
- normalization：啟用 per-frame peak normalization，target peak `12000`、min peak `6000`、max gain `4.0`。

### 第一輪離線結果（2026-09-29）

使用 10 個正樣本與 12 個負樣本、16kHz、20ms frame、啟用 normalization：

| threshold | 正樣本命中 | 負樣本誤觸發 |
|---:|---:|---:|
| 0.25 | 4/10 | 0/12 |
| 0.20 | 4/10 | 0/12 |
| 0.15 | 6/10 | 0/12 |

目前 `0.15 + normalization` 是候選設定，但樣本量太小，尚不能代表 production 表現。

### Smooth RMS AGC A/B 結果（2026-09-29）

使用 `target_rms=3000`、`noise_floor=80`、`max_gain=4.0`、`attack=0.45`、`release=0.12`，threshold `0.15`：

| preprocessor | 正樣本命中 | 負樣本誤觸發 |
|---|---:|---:|
| peak normalization | 6/10 | 0/12 |
| smooth RMS AGC | 6/10 | 0/12 |

目前結果相同，但 smooth AGC 的增益是跨 frame 平滑變化，保留作為後續不同距離與背景噪音測試的候選；正式設定仍維持 peak normalization。

以 far-field dataset 測試 smooth RMS AGC 的 target RMS `3000/6000/9000`、max gain `4/8` 與 noise floor `80/150` 的組合，KWS 在 threshold `0.15` 下皆為 `0/10`。因此單純提高數位增益目前無法救回這批音訊，後續應優先分析訊噪比與音訊特徵，再評估更完整的軟體前處理。

新增 80Hz high-pass / DC removal 並串接 smooth RMS AGC 後，far-field positive 仍為 `0/10`、negative 為 `0/12`。目前沒有召回率改善，但未增加誤觸發；此方案保留為可選前處理，不切換 production default。

### KWS 參數矩陣結果（2026-09-29）

在 threshold `0.15`、peak normalization 下，測試 frame `10/20/30ms`、`num_trailing_blanks=1/2`、`keywords_score=1.0/1.5/2.0`，far-field positive 全部為 `0/10`，negative 全部為 `0/12`。目前模型的 streaming 參數調校沒有改善遠距離低音量召回率，下一階段進入模型評估。

同一組矩陣套用一般距離資料 `recordings/kws/positive/`：

| frame | trailing blanks | keyword score | 正樣本命中 | 負樣本誤觸發 |
|---:|---:|---:|---:|---:|
| 10ms | 1 | 1.0 | 6/10 | 0/12 |
| 20ms | 1 | 1.0 | 6/10 | 0/12 |
| 30ms | 1 | 1.0 | 7/10 | 0/12 |
| 20ms | 2 | 1.0 | 4/10 | 0/12 |
| 20ms | 1 | 1.5 | 6/10 | 0/12 |
| 20ms | 1 | 2.0 | 6/10 | 0/12 |

在 30ms frame 下掃描 threshold `0.10/0.15/0.20/0.25`，結果皆為正樣本 `7/10`、負樣本 `0/12`。目前一般距離的候選設定為 30ms、trailing blanks 1、keyword score 1.0；但它無法改善 far-field dataset。

根據一般距離的結果，暫時將候選參數套用到本機設定：`wake.toml` 使用 threshold `0.15`、score `1.0`、trailing blanks `1`。目前 `myagent.toml` 保留 VAD 20ms，另以 `[wake] frame_ms = 30` 設定 KWS frame，已完成 KWS/VAD 解耦。

### 遠距離 / 低音量結果（2026-09-29）

目前 `recordings/kws/positive/medium/` 的 10 個有效樣本都是使用 production device 3 錄製，實際上屬於遠距離低音量條件；兩個誤用 device 4 且完全靜音的檔案已刪除。有效樣本 peak 約為 `2248–4000`。peak normalization 下：

| threshold | 正樣本命中 | 負樣本誤觸發 |
|---:|---:|---:|
| 0.15 | 0/10 | 0/12 |
| 0.10 | 0/10 | 0/12 |

單純降低 threshold 沒有救回這批遠距離樣本，表示目前主要問題可能是訊噪比、遠場聲學條件或模型特徵不匹配，而不只是 threshold 太高。

同一批音檔交給目前預設的 Qwen3-ASR-0.6B 後，只有 `1/10` 完整辨識為「麥芽糖」，其餘多數產生相近音節。這批資料因此固定作為 far-field regression dataset，不重新錄製。

## 目標架構

```text
RawInputStream 16kHz mono int16
        │
        ├── raw audio tap（診斷、錄音、replay）
        │
        ▼
KWS Audio Preprocessor
  ├── DC / high-pass（必要時）
  ├── noise floor estimation / soft gate
  ├── smooth digital AGC
  └── optional noise suppression
        │
        ├── KWS stream
        └── metrics tap（RMS、peak、gain、VAD、latency）
```

前處理必須是可配置、可關閉、可記錄參數的獨立元件。KWS 與 VAD 的 frame size 應逐步解耦，避免調整 KWS frame 時意外改變語音分段行為。

## 開發階段

### Phase 0：資料與工具基礎

- [x] 確認模型、sample rate、frame 與目前參數。
- [x] 建立 `myagent-kws-record`，互動錄製固定長度 WAV。
- [x] 支援 positive / negative 錄音提示，包含靜音場景。
- [x] 建立 `myagent-kws-replay`，逐檔 reset stream 後離線 replay。
- [x] 輸出每個檔案的 RMS、peak、hit、keyword 與 hit latency。
- [x] 加入可切換的 smooth RMS-based digital AGC。
- [x] 加入可切換的 high-pass / DC removal 前處理。
- [x] 解耦 KWS 與 VAD frame，支援 VAD 20ms / KWS 30ms。
- [x] 建立可切換的 streaming spectral gate 實驗前處理。
- [x] 加入可配置的 VAD minimum speech duration filter。
- [x] 建立 WebRTC VAD offline replay 工具。
- [x] 增加 summary metrics：TPR、FPR、latency percentile 與 replay CPU time。

### Phase 1：建立可比較的資料集

- [ ] Positive：近距離、中距離各至少 10 次。
- [x] Positive：device 3 遠距離低音量 10 次，固定為 far-field regression dataset。
- [ ] Positive：正常音量、低音量、快/慢語速各至少 10 次。
- [ ] Negative：一般句子、相近音、不同說話內容各至少 20 次。
- [ ] Negative：靜音、風扇、鍵盤、播放 TTS / 音樂等背景條件。
- [ ] 錄音時記錄 device、距離、場景、說話方式與實驗參數。

### Phase 2：前處理實驗

固定模型與 threshold，依序比較：

1. Raw audio。
2. 目前 per-frame peak normalization。
3. Smooth RMS-based digital AGC。
4. AGC + noise floor / soft gate。
5. AGC + 輕量 noise suppression。

每一種前處理都要使用同一批 replay data，並輸出 CPU 時間、TPR、FPR 與 latency。所有前處理都必須在不同 device 錄音仍能使用，不能依賴單一硬體特性。

### Phase 2.5：Noise suppression / speech enhancement

此階段同時處理遠距離低音量與 wake 後鍵盤聲誤觸發：

- [ ] 建立 speech、keyboard、環境噪音、靜音的固定 replay dataset。
- [ ] 先做 offline spectral noise suppression / speech enhancement A/B。
- [ ] 比較 enhancement 前後的 STT 可辨識率、KWS TPR、KWS FPR 與音訊失真。
- [ ] 將 enhancement 做成可關閉的 streaming preprocessor，接在 VAD、KWS、STT 共用輸入之前。
- [ ] 增加 VAD temporal gating，避免單次短促雜音直接形成 utterance。
- [ ] 驗證鍵盤聲、拍桌、碰撞聲不會通過 VAD 並送入 STT。

Noise suppression 不會直接視為一定有效：鍵盤聲是短促 broadband transient，單純降噪可能不足，因此必須與 VAD 的連續語音條件、minimum voiced duration 和 post-filter 一起測試。

第一版 spectral gate replay 結果（threshold `0.15`、frame `30ms`）：一般距離 positive `5/10`、far-field positive `0/10`、negative `0/12`。相較 peak normalization 一般距離 `7/10` 沒有改善，因此暫不接入 production；後續優先測試 VAD temporal gating 與實際鍵盤聲資料。

鍵盤聲 VAD replay（10 個樣本）顯示：aggressiveness `2` 時接受 `7/10`，aggressiveness `3` 時接受 `1/10`；minimum speech duration `300/500/700ms` 在 aggressiveness `2` 下皆無明顯差異。aggressiveness `3` 對一般距離與 far-field 正樣本仍為 `10/10`，因此已套用到本機 `myagent.toml`，minimum speech duration 維持 `300ms`。

### Phase 3：KWS 參數調校

前處理固定後比較：

- threshold：`0.15`、`0.20`、`0.25`、`0.30`。
- `keywords_score`：維持 `1.0`，必要時才測試提高值。
- `num_trailing_blanks`：`1`、`2`，觀察誤觸發與延遲。
- KWS frame：`10ms`、`20ms`、`30ms`；需與 VAD frame 分離後再測。
- sample rate：先固定 16kHz，只有在硬體相容性問題時才考慮其他設定。

### Phase 3.5：模型替換評估

只有在軟體前處理與參數調校仍無法達到低音量資料的最低驗收標準時，才進入模型替換：

- [ ] 盤點支援中文自訂 keyword、16kHz streaming input 與本地 CPU inference 的候選模型。
- [ ] 確認候選模型是否能直接支援「麥芽糖」，或需要重新訓練 / fine-tune。
- [ ] 以相同 positive / negative replay dataset 做模型 A/B。
- [ ] 比較召回率、誤觸發率、延遲、模型大小與 CPU 成本。
- [ ] 保留現有 Sherpa-ONNX 模型作為 fallback。

### Phase 4：線上整合與回歸

- [ ] 將候選前處理接入 live microphone path。
- [ ] 保留一個 config flag，可快速切回 raw / current normalization。
- [ ] 驗證 wake detection 不影響 VAD、STT、wake buffer 與 interrupt 行為。
- [ ] 驗證長時間運行 CPU、記憶體與 audio callback 穩定性。
- [ ] 用相同錄音資料重跑 offline regression。

### Phase 5：正式採用或退回

- [ ] 明確記錄選定參數與原因。
- [ ] 更新 `wake.toml`、README 與本 plan。
- [ ] 建立 checkpoint commit。
- [ ] 若沒有達到驗收標準，保留實驗工具與結果，不修改 production 預設值。

## 暫定驗收標準

以下是第一版暫定門檻，會隨資料集擴大再校正：

- Clean / normal-volume TPR：至少 90%。
- Low-volume / distance TPR：至少 80%。
- Negative FPR：在至少 30 分鐘混合負樣本 replay 中低於 1 次。
- Wake detection latency：p95 不超過 500ms，且不明顯增加 audio callback backlog。
- 前處理 CPU 使用量：在目前硬體上不可造成可感知的 listening / TTS 延遲。

## 觀測與報告格式

每次實驗至少記錄：

```text
dataset=
preprocessor=
threshold=
keywords_score=
num_trailing_blanks=
frame_ms=
sample_rate=
positive_total=
positive_hits=
negative_total=
negative_hits=
latency_p50=
latency_p95=
cpu_time=
```

## 風險與注意事項

- Per-frame peak normalization 可能放大背景噪音，也可能造成 frame 邊界音量跳動。
- 強降噪可能扭曲 wake word 的音素特徵；所有 NS 都必須用正負樣本 A/B 測試。
- VAD 太嚴格可能擋掉低音量 wake word，因此不能只用 VAD 作為唯一 gating 條件。
- Noise suppression 可能削弱低音量語音或改變音素特徵；必須同時用正樣本、負樣本與 STT 結果驗證。
- 鍵盤聲誤觸發不一定能只靠降噪解決，必須觀察 VAD 的連續 frame 行為與 utterance start threshold。
- 正樣本與負樣本目前數量仍少，現階段結果只能用於方向判斷。
- 播放 TTS 時若要支援喚醒，需要另外評估 AEC；單純 AGC / NS 無法解決回音。
- 不以特定硬體的 microphone gain、距離或 device profile 掩蓋模型與前處理問題；device 差異應由統一 software preprocessing 吸收。

## 使用工具

錄製正樣本：

```bash
uv run --no-sync myagent-kws-record \
  --kind positive --count 10 --duration 2.0 --device 4
```

錄製帶提示的負樣本：

```bash
uv run --no-sync myagent-kws-record \
  --kind negative --count 12 --duration 2.0 --device 4
```

離線 replay：

```bash
uv run --no-sync myagent-kws-replay \
  --input-dir recordings/kws/positive --threshold 0.15

uv run --no-sync myagent-kws-replay \
  --input-dir recordings/kws/negative --threshold 0.15
```

## 下一步

1. 在現有 dataset 上加入高通 / DC removal 與 noise floor-aware 前處理實驗。
2. 重跑 peak / smooth RMS AGC A/B，並同步比較 STT 可辨識率與 KWS 命中率。
3. 完成 threshold、trailing blanks 與 frame size 的參數矩陣。
4. 若仍未達標，盤點並接入候選中文 KWS 模型做 A/B。
5. 只有離線結果達標後，才把候選方案接回 live KWS。
