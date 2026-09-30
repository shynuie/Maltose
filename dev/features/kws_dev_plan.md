# KWS 優化開發計畫

## 文件狀態

- 狀態：`in_progress`
- 最後更新：2026-09-30
- 目前階段：KWS 模型評估
- 正式設定：已套用一般距離候選參數，far-field 進入模型評估

## 目標

提升 wake word「麥芽糖」在實際麥克風、不同距離、音量與背景噪音下的召回率，同時控制誤觸發、延遲與 CPU 成本。

本階段新增模型評估與訓練目標：在不依賴特定 audio device 的前提下，評估中文 far-field KWS 模型是否能改善目前 Sherpa-ONNX baseline 的遠距離召回率；只有通過離線 benchmark 與線上回歸測試，才替換 production model。

## 非目標

- 在完成現有模型的前處理、參數與 variant baseline 前，不直接更換 Sherpa-ONNX KWS 模型；目前已完成 baseline，進入候選模型評估。
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

### Peak normalization target sweep（2026-09-29）

為確認 `target_peak=12000` 是否有實驗依據，固定 threshold `0.15`、KWS frame `30ms`、`num_trailing_blanks=1`、`keywords_score=1.0`，並固定 `min_peak=6000`、`max_gain=4.0`，只改變 target peak。`target=0` 代表 raw input。

| target peak | 一般距離 positive | far-field positive | negative |
|---:|---:|---:|---:|
| raw | 5/10 | 1/10 | 0/12 |
| 3000 | 4/10 | 1/10 | 0/12 |
| 5000 | 6/10 | 1/10 | 0/12 |
| 8000 | 7/10 | 0/10 | 0/12 |
| 12000 | 7/10 | 1/10 | 0/12 |
| 16000 | 7/10 | 1/10 | 0/12 |

結論：在目前資料集上，`8000/12000/16000` 的一般距離召回表現相同，沒有證據顯示 `12000` 優於其他高 target；far-field 也沒有因 target 提高而改善。`12000` 應視為保留 headroom 的初始 heuristic，而非已驗證的最佳值。現階段 production 仍保留 `12000`，後續若要降低噪聲放大風險，可優先比較 `8000`。

### KWS 模型評估（進行中）

Normalization target sweep 顯示目前模型在 far-field 資料上的召回率沒有改善，因此開始評估更換 KWS 模型。評估原則：先保留現有 Sherpa-ONNX Zipformer 作 baseline，使用相同的 normal positive、far-field positive、negative 資料，以及相同的 latency/CPU 指標；候選模型只有在可以公平 replay、且不增加負樣本誤觸發時才考慮接入 production。

第一輪先測試同一模型包內可替換的 streaming / quantization variant，固定 threshold `0.15`、KWS frame `30ms` 與 peak normalization：

| variant | 一般距離 positive | far-field positive | negative |
|---|---:|---:|---:|
| chunk 8 / int8（目前 baseline） | 7/10 | 1/10 | 0/12 |
| chunk 8 / float | 7/10 | 1/10 | 0/12 |
| chunk 16 / int8 | 3/10 | 1/10 | 0/12 |
| chunk 16 / float | 2/10 | 2/10 | 0/12 |

結論：chunk 16 雖然在 far-field 多命中一個樣本，但一般距離召回明顯下降，不能作為目前 production 替代方案；chunk 8 的 float 與 int8 表現相同，量化不是主要瓶頸。下一步需要引入真正不同訓練資料或架構的中文 KWS 候選模型，繼續使用同一 replay benchmark。

#### openWakeWord 初步評估

- 可行性：技術上可透過 Python adapter 接入 16kHz streaming audio，並保留現有 `WakeWordDetector` 介面。
- 主要限制：官方 upstream 目前明確以英文為主要支援語言；自訂模型雖可透過合成資料訓練，但官方訓練流程的預訓練 TTS／資料 pipeline 不是針對中文設計。
- 對「麥芽糖」的判斷：不能直接假設英文模型或官方 baseline 可用；若採用，必須取得真正的中文 custom ONNX/TFLite model，並以本機 positive/negative/far-field dataset 重新 benchmark。
- 決策：列為候選技術驗證，不立即替換 production。優先確認中文模型來源、授權、輸入 frame 約束、CPU latency 與模型在 macOS 上的 runtime 相容性。

### 模型評估與訓練計畫

#### 目標與決策原則

- Production baseline：目前的 Sherpa-ONNX Zipformer 中文／英文 KWS，chunk 8、int8、30ms KWS frame。
- 第一候選：ModelScope／阿里語音 KWS 系列，優先評估中文 far-field 模型與 custom keyword training suite。
- 第二候選：openWakeWord 中文 custom model；只有在取得實際可用的中文 ONNX/TFLite model 後才進行 benchmark。
- 不以單一 positive recall 作為唯一標準；任何候選模型都必須同時比較 recall、false positive、latency、CPU 與記憶體。
- 不直接把實驗模型接到 live agent；所有候選先透過 offline replay，再做 shadow/live monitor，最後才修改 `wake.toml`。

#### 評估資料集分層

資料集固定拆成 train、validation、test 三組，test 集在模型選定前封存，不參與調參：

| split | 用途 | 建議內容 |
|---|---|---|
| train | 訓練模型 | 正樣本、合成變體、背景噪聲與混音 |
| validation | 選 threshold、模型與 preprocessing | 不與 train 重複的真人／房間／距離組合 |
| test | 最終驗收 | 封存的 normal、far-field、noise、hard negative |

目前已存在的錄音先作 validation/test，不直接全部拿去訓練：

- normal positive：`recordings/kws/positive/`
- far-field positive：`recordings/kws/positive/medium/`
- ordinary negative：`recordings/kws/negative/`
- keyboard negative：`recordings/kws/negative/keyboard/`

後續每一個檔案需保留 metadata：speaker、device、距離／房間、噪聲類型、peak、RMS、sample rate、split 與錄音日期。

#### Phase A：先驗證預訓練模型與 runtime

1. 建立隔離的 ModelScope／阿里 KWS 實驗環境，不污染目前 `uv` production dependencies。
2. 下載一個中文 far-field 預訓練模型，例如固定喚醒詞的 demo model，只驗證 runtime、輸入格式與 CPU 成本。
3. 確認 ModelScope pipeline 是否能讀本地 WAV、是否可離線執行，以及模型輸出是否能取得 detection score／latency。
4. 若模型只支援固定喚醒詞，標記為 runtime proof，不把它當成「麥芽糖」效果結果。
5. 建立 `AlibabaKWSDetector` adapter 的最小 prototype，暫不接入 live microphone。

#### Phase B：小規模「麥芽糖」訓練可行性驗證

第一輪不追求 production 規模，目標是確認訓練流程能否產出可用模型：

- 真人正樣本：Marvin 約 100～300 句，涵蓋正常距離、遠距離、小聲、快慢語速與不同房間位置。
- 合成正樣本：約 1,000～5,000 句，用於補足發音、語速與文字變體；合成資料不可取代真人 far-field validation。
- 真人 hard negative：包含普通對話與容易混淆的音，例如「麥芽」、「買牙套」、「沒有他」、「那也對」等。
- 環境 negative：鍵盤、風扇、電腦播放聲、TTS 回音、音樂、電視與靜音。
- 音訊統一：16kHz、mono、16-bit PCM；保留原始錄音，不覆蓋原檔。

這一階段的結果只用來判斷「是否值得擴大資料」，不直接決定 production replacement。

資料 pipeline prototype 已開始：

- `myagent-kws-record` 新增 `speaker-id`、`distance`、`environment` 與 JSONL metadata 輸出。
- 每段錄音會保存 path、kind、keyword、device、sample rate、duration、RMS、peak 與 timestamp。
- 新增 `myagent-kws-manifest`，可將 WAV 目錄整理成 train／validation／test JSONL manifest，並避免重複掃描同一檔案。
- 目前既有錄音已建立 baseline test manifest，共 52 筆；既有資料 metadata 不完整，後續新錄音需使用明確 speaker／distance／environment 標籤。

2026-09-30 新增 Marvin 90 句正樣本（device 3、16kHz、quiet environment）：

| distance | samples | RMS 範圍 | peak 範圍 | Sherpa baseline hits | recall |
|---|---:|---:|---:|---:|---:|
| near | 30 | 687–1316 | 5003–9705 | 18/30 | 60.0% |
| normal | 30 | 340–1311 | 3177–11728 | 13/30 | 43.3% |
| far | 30 | 168–504 | 1451–4054 | 3/30 | 10.0% |

Replay 固定使用目前 Sherpa baseline、30ms KWS frame、peak normalization、threshold `0.15`。三組資料都來自同一位 speaker 與同一個 device，因此這不是 speaker/device 泛化測試，但已足以確認目前模型的 distance degradation：遠距離 recall 顯著低於近距離與正常距離。錄音 metadata 已由 `myagent-kws-manifest` 讀取並保留，後續 manifest 不應把 near／normal／far 合併成無標籤資料。

已產生 `data/kws/manifests/marvin-positive-validation.jsonl`，共 90 筆，並保留 `near/normal/far`、speaker `marvin`、device `3`、RMS、peak 與錄音時間等欄位。該 manifest 屬於 validation candidate，不會直接當成 train set。

目前判斷：90 句正樣本可作為第一輪 validation candidate，但不足以直接訓練或驗收「麥芽糖」模型。下一個必要資料集是 negative 與 hard-negative，並且要包含鍵盤、環境聲、普通對話、相近音與靜音，才能開始判斷模型是否只是在降低 threshold 後增加誤觸發。

2026-09-30 已新增 10 段 Marvin ordinary speech negative（device 3、normal distance、quiet-speech），目前 Sherpa baseline 誤觸發為 `0/10`。其中包含 1 段靜音，後續仍需補充相近音與真實環境噪音，不能以這 10 段代表完整 negative test。

同日新增 10 段 hard-negative candidate（device 3、normal distance、quiet-hard-negative）：其中 9 段有效相近音全部未命中（`0/9`），第 10 段因提示句「麥芽糖很好吃，但不要喚醒」含有完整 wake word，baseline 命中屬於預期結果，已標記為不可納入 negative benchmark。後續錄音 metadata 會保存實際 prompt，避免再混入這類樣本。

目前 30 段本地負樣本已建立 `data/kws/manifests/marvin-negative-validation.jsonl`：ordinary speech 10、hard-negative candidate 10、mixed environment noise 10。外部場景聲的來源與授權規則整理在 `dev/features/kws_noise_sources.md`；下一步先導入可追溯的 MUSAN／CC0 音效，再做混音與 replay，不直接把網路音檔當成正式 test set。

2026-09-30 已下載 ESC-50 官方 repository archive 至 `data/kws/external/esc50/`，解壓後約 846MB。ESC-50 共 2,000 段、50 類環境聲，授權為 CC BY-NC；目前只作內部研究／stress test。下一步只抽取鍵盤、滑鼠、家電、風、雨、引擎與敲門等相關類別，轉成 16kHz mono 後建立 external negative manifest，不把完整資料集提交到 git 或直接當成 production test set。

已抽取 8 類、每類 10 段，共 80 段 16kHz mono external negative，manifest 為 `data/kws/manifests/esc50-negative-stress.jsonl`。目前 Sherpa baseline 在這批資料上的誤觸發為 `0/80`；這只能說明目前 threshold 對這批場景聲穩定，不能代替真實麥克風混音測試。為支援分類子目錄，`myagent-kws-replay` 已改為遞迴尋找 WAV。

已新增 `myagent-kws-mix`，將 90 段 Marvin 正樣本與 ESC-50 噪音隨機混合，產生 0／5／10／20 dB SNR，各 90 段，共 360 段；manifest 為 `data/kws/manifests/marvin-positive-esc50-mixed-validation.jsonl`。Sherpa baseline replay 結果：

| SNR | 命中 | recall |
|---:|---:|---:|
| 0 dB | 15/90 | 16.7% |
| 5 dB | 24/90 | 26.7% |
| 10 dB | 26/90 | 28.9% |
| 20 dB | 28/90 | 31.1% |

總體為 93/360（25.8%）。這是單次隨機 noise pairing 的初始結果，不直接作模型 replacement 判斷；後續需固定 noise source、重複 seed，並與 clean positive 按相同 distance 分層比較。

已用 seed `20260930`、`20260931`、`20260932` 重複相同的 360 段混音實驗。三次結果如下，括號為三個 seed 的 population standard deviation：

| SNR | seed 20260930 | seed 20260931 | seed 20260932 | 平均 recall |
|---:|---:|---:|---:|---:|
| 0 dB | 16.7% | 17.8% | 14.4% | 16.3% ± 1.4% |
| 5 dB | 26.7% | 27.8% | 21.1% | 25.2% ± 2.9% |
| 10 dB | 28.9% | 28.9% | 31.1% | 29.6% ± 1.0% |
| 20 dB | 31.1% | 30.0% | 32.2% | 31.1% ± 0.9% |

結論：噪音強度與 recall 的下降關係在三個 seed 下都存在，結果不是單次 noise pairing 造成的偶然。這批資料現在可作為後續 custom KWS training／enhancement 的 validation stress set，但不能直接拿來宣稱新模型效果。

已建立第一版 ModelScope KWS training-suite candidate list：`data/kws/training/marvin-mini/`。正樣本依距離隔離：train 使用 near／normal 的 60 段 clean 加 240 段混音，validation 使用 far 的 30 段 clean 加 120 段混音；negative train 為 19 段 ordinary／有效 hard-negative，negative validation 為 10 段本地 environment，noise train 為 80 段 ESC-50-derived noise。這是 feasibility dataset，只有一位 speaker 與一個 device，不能作 production model 的泛化證明。

官方 ModelScope KWS training suite 使用 16kHz mono PCM WAV，並透過每行一個絕對路徑的 `.txt` list 讀取正樣本、負樣本與噪聲；官方也建議實際場景自行錄製資料，而不是完全依賴公開資料。[官方資料準備說明](https://github.com/modelscope/kws-training-suite/blob/main/README.md)

### macOS 本機訓練阻塞點（2026-09-30）

已在隔離 Python 3.10 環境下載官方 `kws-training-suite`，並補齊 `librosa` 等最小依賴。套件的 `pipeline.py --help` 可以啟動，但 `force_align.py` 使用的 `bin/lt-force_align` 是 Linux x86-64 ELF native binary；目前開發機是 macOS Apple Silicon，無法執行，因此 60 段正樣本 alignment 沒有產生有效輸出。官方 `SoundConnect`／評估流程同樣依賴 Linux native components。

判斷：本機可以繼續完成資料清理、混音與 manifest 準備，但正式 force alignment、custom model training 與官方 ROC evaluation 需要 Linux x86-64（最好搭配 CUDA GPU）環境。下一步應優先準備 Docker／Linux runner 或遠端 GPU workspace，再把 `data/kws/training/marvin-mini` 與 alignment input 搬過去；不在 macOS 上修改 native binary。

### 遠端 training server 狀態（2026-09-30）

- Server：Ubuntu 22.04、x86-64、Tesla V100 32GB、NVIDIA driver 535.113.01、Python 3.10.12。
- 已建立 `/root/myagent-kws/venv`，安裝 PyTorch 2.2.2 + CUDA 12.1、ModelScope 1.25.0、librosa；`torch.cuda.is_available()` 已驗證為 `True`。
- 已上傳 training candidate、混音資料、80 段 external noise 與 manifests，並 clone 官方 `kws-training-suite`。
- host 直接執行 `lt-force_align` 時 exit 139 segfault；已安裝 Docker 並開始拉官方 Ubuntu 20.04／CUDA 11.3／PyTorch 1.11 image，但 pull 因網路長時間無進度暫停，尚未執行 container alignment。
- 尚未開始正式訓練；下一個 gate 是在官方 container 內完成單檔 alignment smoke test，確認成功後才批量 alignment。

#### Phase C：真人 speaker diversity 擴充

若 Phase B 有改善，再擴充至：

- 10～20 位真人 speaker
- 每人 30～50 句正樣本
- 每人 30～60 秒不含 wake word 的普通語音
- 每個 speaker 至少涵蓋一種不同距離或房間條件

若模型已顯示穩定改善，再考慮接近官方訓練建議的規模。官方 KWS training suite 提到約 100 人 × 100 句正樣本，以及大量負樣本／噪聲資料；這是完整 production 訓練規模，不是第一輪必要門檻。

#### Phase D：公平 benchmark 與驗收

每個候選模型使用同一套 replay runner 與相同 test 集，至少記錄：

| 指標 | 驗收方向 |
|---|---|
| normal recall | 不低於目前 baseline，最好提升 |
| far-field recall | 必須明顯高於目前 baseline `0～1/10` |
| hard-negative false positive | 不得比 baseline 惡化 |
| keyboard false positive | 不得比 baseline 惡化 |
| detection latency | 記錄 p50/p95，不接受明顯增加 |
| CPU／memory | 可在目前 macOS CPU 長時間運行 |
| input compatibility | 16kHz mono streaming，能接現有 listener |

暫定 replacement gate：

- normal positive recall 至少 `>= 90%`，或比 baseline 有明確提升且無誤觸發惡化；
- far-field positive recall 至少比 baseline 提升 30 percentage points；
- negative 與 keyboard false positive 不高於 baseline；
- 連續運行 30 分鐘無 audio callback、memory 或 thread 穩定性問題。

#### Phase E：整合與回退

- 新增 provider／adapter config，不覆蓋現有 Sherpa implementation。
- `wake.toml` 保留 `provider = "sherpa-onnx"` 作為 fallback。
- 新模型先以 replay CLI 驗證，再以 live monitor 做 shadow test。
- 只有完成 test report、runtime soak test 與手動語音測試後，才切換 production default。
- 所有模型檔、版本、checksum、threshold 與資料集版本寫入 plan。

#### 阿里「小云」/ ModelScope KWS 初步評估

- 目前查到的可用資源主要是 ModelScope 的 KWS 模型與 `modelscope/kws-training-suite`，不是一個可直接替換的單一 `xiaoyun` runtime 套件。
- `damo/speech_dfsmn_kws_char_farfield_16k_nihaomiya` 是 16kHz 中文 far-field KWS 範例模型，但固定喚醒詞是「你好米雅」；`speech_charctc_kws_phone-xiaoyun` 則是「小云」系例的固定模型，不能直接辨識「麥芽糖」。
- 官方訓練套件支援自訂中文喚醒詞，但完整訓練需求很重：至少約 100 人 × 100 句正樣本，並需要大量負樣本與噪聲資料；文件列出的推薦環境包含 GPU、約 400GB 儲存，完整流程可能需要數十小時。
- 推理格式也與目前 Sherpa-ONNX 不同：範例使用 ModelScope pipeline，訓練套件的產物包含 PyTorch checkpoint 與供其 SoundConnect 使用的 `.txt` 模型參數，不是現成 ONNX。
- 判斷：這條路比 openWakeWord 更符合中文與 far-field 方向，但若要用「麥芽糖」，需要自行訓練或取得 custom model；目前先不引入主環境，下一步先確認預訓練模型在 macOS CPU 上可否離線 replay，再評估 adapter 或模型轉換成本。

Phase A runtime probe（2026-09-29）結果：

- 已在 `/private/tmp/myagent-modelscope-kws-venv` 建立隔離環境，沒有修改 production `.venv` 或 `pyproject.toml`。
- 已下載 `damo/speech_dfsmn_kws_char_farfield_16k_nihaomiya` 模型快取。
- ModelScope pipeline 可以載入，但模型初始化被 `py_sound_connect` 的 Python 版本限制阻擋：目前 runtime 要求 Python `<=3.10`，本機主環境是 Python `3.12`。
- 因此目前尚未取得該模型在本機的 recall、latency 或 CPU benchmark；下一步需建立 Python 3.10 legacy runtime，或研究模型檔能否脫離 `py_sound_connect` 直接轉換／推論。

後續補充結果：

- 已安裝 Python `3.10.19` 與隔離 venv `/private/tmp/myagent-kws310`。
- 已成功安裝 `py_sound_connect 0.2.1`、PyTorch `2.14.0`、ModelScope `1.40.1` 與最小 KWS pipeline 依賴。
- 官方 sample `3ch_nihaomiya.wav` 成功在 CPU 偵測到 5 次 `0_ni_hao_mi_ya`，證明官方 runtime 與 SoundConnect 可在本機運行。
- 使用目前「麥芽糖」資料做固定 keyword 模型的 smoke test：normal `0/10`、far-field `0/10`、ordinary negative `0/12`、keyboard `0/10`。這只代表模型沒有把「麥芽糖」資料誤判成「你好米雅」，不能作為「麥芽糖」召回率結果。
- 目前每個短 WAV 的 pipeline CPU wall time 約 10～15ms；這是 file pipeline 的粗略 smoke-test 數字，不等同於正式 streaming latency。
- 完整 `modelscope[audio]` extra 在 Python 3.10 仍會被無關的 `MinDAEC==0.0.2` wheel 阻擋，因此實驗環境採用最小依賴安裝；production 不引入這些依賴。

#### 隔離 runtime 與 IPC 架構

阿里 KWS runtime 需要 Python `<=3.10`，主 agent 維持 Python `3.12`；兩者採用獨立 process：

```text
主 agent（Python 3.12）
    └── AlibabaKWSDetector adapter
          └── KWS worker（Python 3.10 + ModelScope + py_sound_connect）
```

- 第一版由主 agent 啟動並監控 worker，worker 啟動時載入模型一次。
- 音訊 frame 使用 binary length-prefixed protocol 傳送，避免 base64 與 JSON 膨脹。
- 控制訊息使用簡單 JSON：`reset`、`health`、`shutdown`。
- 偵測結果回傳 JSON event：keyword、confidence、offset、worker model version。
- 本機 IPC 優先採 Unix domain socket；若只需要單一 child process，亦可先用 stdin/stdout 做最小 prototype。
- 不使用 HTTP：不需要網路語意，且 per-frame request overhead 較高。
- 不使用 UDP：KWS streaming state 不應承受 frame 遺失或重排。
- worker 無回應或崩潰時，adapter 必須回報 unavailable 並保留 Sherpa-ONNX fallback，不可阻塞主 agent listening loop。

第一版 IPC prototype 已完成：

- `myagent/voice/alibaba_kws.py`：Python 3.12 主 process adapter。
- `myagent/voice/alibaba_kws_worker.py`：Python 3.10 ModelScope worker。
- `myagent/kws_protocol.py`：length-prefixed binary stdin/stdout protocol。
- 已完成端到端測試：主 process 啟動 Python 3.10 worker，傳送官方 sample 的 mono PCM，成功回傳 5 次 `0_ni_hao_mi_ya` detection。
- 目前尚未切換 `wake.toml` production provider；下一步是加入 worker lifecycle timeout、崩潰 fallback 與 offline replay adapter benchmark。

後續 prototype 補強：

- adapter 已加入 worker startup／response timeout，worker 無回應時會終止子程序並回報 `AlibabaKWSProcessError`。
- worker `reset` 已改成只重建 SoundConnect streaming state，不重新載入 PyTorch／ModelScope 模型。
- `wake.py` 已讓 Alibaba provider 共用既有 KWS normalization wrapper。
- 新增 `dev/features/wake.alibaba.example.toml`，只作實驗設定，不切換 production `wake.toml`。
- `myagent-kws-replay` 已能透過此 provider 執行 offline replay；目前固定 keyword demo 對「麥芽糖」資料的結果仍只作 smoke test。
- 已新增 `FallbackWakeWordDetector` 與 `wake.alibaba.example.toml` 的 `fallback_config`；Alibaba worker 發生 exception 時會切換到 Sherpa-ONNX，並把當前 frame 交給 fallback。
- fallback 行為已用故障注入測試確認，後續仍需加入完整 worker crash／timeout integration test。
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

1. 由 90 句正樣本建立保留 metadata 的 validation manifest，並封存檔案清單。
2. 錄製並標記第一批 negative／hard-negative，優先覆蓋普通語音、相近音、鍵盤、背景聲與靜音。
3. 用同一套 replay runner 比較 Sherpa baseline、ModelScope custom model 與後續訓練 checkpoint。
4. 只有在 negative false-positive 可量化、且 validation recall 有改善後，才進入「麥芽糖」小規模訓練。
5. 通過離線 benchmark 後，再做 live shadow test；未達標時保留 Sherpa fallback。

## 2026-09-30 進度更新

- 已完成訓練伺服器的基本環境驗證：Ubuntu 22.04 x86_64、Tesla V100-SXM2 32GB、Python 3.10、PyTorch 2.2.2 + CUDA 12.1，CUDA smoke test 通過。
- 已將資料與 ModelScope repository 部署到 `/root/myagent-kws`；本機 macOS ARM 無法執行官方 `lt-force_align` ELF binary，因此訓練流程改在遠端 Linux 執行。
- 遠端直接執行官方 force alignment 時遇到 binary segmentation fault；官方舊版 ModelScope Docker image 可作為下一個隔離驗證路線。
- 官方 image 約數 GB，從北京 registry 可以持續下載但速度偏慢；目前保留 Docker layer cache，尚未開始正式訓練。
- 已完成官方 image pull（約 8.14GB），並安裝 NVIDIA Container Toolkit 1.20.1；容器可使用 Tesla V100，PyTorch 1.11.0 `cuda=True`。
- 官方 `force_align.py` 在容器內可正常執行；使用繁體「麥芽糖」會被詞典拒絕，但使用簡體「麦芽糖」已完成單檔 alignment smoke test。後續標註流程先使用簡體字描述符，產品層仍保留繁體喚醒詞顯示。
- 遠端 manifest 需要把本機 `/Users/Marvin/Workspace/MyAgent` 路徑轉換為 `/root/myagent-kws`；批次 alignment 前會先產生 remote manifest，避免把本機路徑直接交給容器。
- 下一個 checkpoint：完成 60 筆 clean positive 的批次 alignment，檢查輸出品質後再決定是否擴展到 mixed positive 與正式訓練。
- 60 筆 clean positive 已在 GPU container 中完成 alignment，輸出 60 個對齊 WAV，沒有失敗項。
- 30 筆 far positive validation 也已完成 alignment，輸出 30 個對齊 WAV，沒有失敗項。
- ModelScope alignment 輸出本身是 stereo 16k WAV：channel 0 為音訊、channel 1 為 label；不可再用一般 mono-to-stereo duplication 覆寫第二個 channel。`kws_stereo_prepare.py` 僅適用於沒有 label channel 的 negative／test audio。
- 短版 pipeline smoke training 已能啟動 CUDA 與 validation，但目前尚未產生有效 checkpoint；先停止所有 smoke container，避免在資料格式未釐清前浪費 GPU。
- 對齊輸出的 label channel 已實測為三段 int16 值 `327 / 655 / 983`（對應 `LABEL_GAIN=100` 的 1、2、3），因此下一步需對照 SoundConnect 的 label decode 規則，不應直接把 label channel 當一般 stereo 音訊重新 normalize 或 duplication。
- 已從官方 `KWSDataset` 確認：`label * 100` 後以 `numclasses=4` 解讀三音節 `1/2/3`，因此目前 `327/655/983` 的 1-based 編碼是正確的，不應改成 0-based，也不應調整 `LABEL_GAIN`。
- 已從官方設定說明確認：`test_pos_data_dir`／`test_neg_data_dir` 是實際裝置多通道 WAV，預設為 `2 麥克風 + 1 參考 = 3 聲道`；alignment WAV 的第二聲道是 label，只能放在 `train_pos_list`，不能直接當測試音訊。
- 目前的 `3,3` label warning 與 `1/2` channel mismatch 應視為 smoke fixture／測試資料格式問題，而不是先修改模型或標籤編碼。下一步改建立 3 聲道 test fixture，並以原始 positive／negative 音訊及 `test.txt` annotation 做最小 evaluator 驗證；驗證通過後才重新啟動短版訓練。
- 已建立遠端 3 聲道測試 fixture：30 筆 far positive、10 筆 ordinary negative，並建立官方格式的 `test.txt` annotation；抽查結果均為 16 kHz、`(samples, 3)`。
- 最小 base-only smoke 顯示：移除錯誤的 `train_noise2_list`（該欄位會把單聲道 noise 當成多聲道 noise）後，`No. of audio channels not match: 1, 2` 不再出現；原本的 label `3,3` 僅剩官方 native warning，資料 loader 能繼續產生 validation batch。
- 這次 smoke 沒有產生 checkpoint，原因是 `max_epochs: 1` 對官方三階段 trainer 會被視為無效 epoch；下一次需使用至少足以跑完 base stage 的小輪數，並保留正確的單聲道 noise 設定。
- 已改用 `max_epochs: 10`（官方三階段比例因此為 `1/6/3`），並以每 epoch 2 batches、validation 1 batch 執行 base-only smoke；目前已產生至少 3 個 checkpoint，validation loss 從 `1.2797` 降至 `0.8738`。
- 這輪執行中未再出現 `No. of audio channels not match: 1, 2`；訓練容器仍在執行，待完成後再收集最終 checkpoint／model conversion 結果。
- base-only smoke 已完成 10 epochs，產生 `first_txt/top_01_checkpoint_0010_loss_train_0.6061_loss_val_0.5888.txt`；validation loss 降至 `0.5888`。
- ROC 評估已修正 annotation fixture：官方 evaluator 實際會把 `test_pos_anno_dir` 當作 positive WAV 輸入目錄，因此 annotation scene 必須同時包含 `test.txt` 與 WAV。評估容器另需相容的 OpenJDK 11；主機 Java 18 因 glibc 不相容不能直接掛載。
- 首次有效 ROC 結果：30 筆 far positive 的 `mai_ya_tang` recall 為 `0/30 = 0%`；ordinary negative 未產生喚醒。這個 smoke checkpoint 目前不可用於產品，下一步需檢查模型輸出／keyword descriptor／測試聲道與訓練資料的對應，再進行下一輪訓練。
- 進一步發現先前 3 聲道測試 fixture 將語音複製到 reference channel，會讓 AEC 把語音當回聲消除；已修正為 `mic1=語音、mic2=語音、reference=靜音`，並擴充 `kws_stereo_prepare.py --silent-last-channel`。正在重新跑 overfit sanity check，尚未取得新 recall 結果。
- 修正 reference 為靜音後，使用同一 checkpoint 做訓練集 overfit sanity check 仍為 `0/30`；因此不能再把目前失效單純歸因於 far-field 或測試 reference fixture。
- 目前第一優先 blocker 是訓練期間反覆出現的 native `Label index out of bounds: ..., 3, 3`。雖然 Python `KWSDataset` 將 `1/2/3` 映射到 `numclasses=4` 的設計看似合理，但 native SoundConnect 可能因此跳過／錯誤處理最後一個 keyword label，導致模型實際沒有學到可偵測的完整序列。下一步先建立 label mapping A/B fixture，確認 native 可接受的 label index，再重新訓練；暫不增加正式資料量。
- 0-based descriptor 實驗（`mai_ya_tang,0,1,2` + `train_pos_list` 的 `0_1_2` mapping）仍出現完全相同的 `3,3` warning，初步排除單純 descriptor 數字偏移；該 smoke 仍可產生 checkpoint，validation loss 已由 `1.0910` 降至 `0.4538`（執行中）。下一步需直接檢查／轉換 alignment WAV 的 label channel，或使用官方已驗證的 label fixture，不能只改 YAML descriptor。
- 已再次對照官方 `force_align.py` 與 `kws_align.py`：官方確實以 `i + 1` 寫入 label，並以 `label / LABEL_GAIN` 還原，因此原始 `1/2/3` 不是我們自行猜測的錯誤格式。0-based mapping smoke 已完成並產生推理 txt，但 native warning 仍存在；目前不能直接把 label 改成 0-based，需先建立可觀察 native label 解碼結果的最小 fixture或對照官方四音節 baseline。
- 已完成四狀態 synthetic label A/B：建立 `1/2/3/4` 四段 label 的 stereo 16 kHz fixture，修正 manifest 的實際換行並掛載 recordings 後，官方 pipeline 可完整跑完 10 epochs；本輪 `Label index out of bounds`、`Unsupported audio format`、`Cannot open input file` 均為 0。這確認 native pipeline 可接受四狀態，先前的 `3,3` warning 不是由「模型只能有三個 label」直接造成。
- 四狀態 smoke checkpoint 為 `work-fourstate-smoke3/first_txt/top_01_checkpoint_0008_loss_train_0.9279_loss_val_0.8794.txt`；對 30 筆 far positive 的 recall 仍是 `0/30`，但該模型只用一個 synthetic training file，不能作為資料量或泛化能力結論。下一步應以正確 1/2/3 alignment label、完整 clean positive manifest 與可重現的 3ch test fixture，拆分檢查「訓練資料讀取／模型輸出／native decode」三段，而不是再改成 0-based。
- 60 筆真實 alignment 的 0/1/2 label A/B 已完成：native warning 從 `3,3` 變成 `2,2`，但仍存在；checkpoint `work-3ch-label012-real` 的 validation loss 為 `0.3891`，far recall 仍為 `0/30`。這證明單純重編碼 label 不足以修正 native loader。
- 已檢查官方 trainer：`_num_classes` 確實取自 pipeline 的 `num_syn`，而預訓練模型 configuration 固定為 `num_syn=5`；提高 descriptor 到 `num_syn=6` 仍維持 `3,3` warning，因此 warning 並非單純由 neural network output class 容量造成。
- 將真實三段 alignment 的最後一段拆成兩個連續 label，形成 60 筆 `1/2/3/4` split4 dataset；該資料在 training/validation 初段完全沒有 native label warning。第一輪因 descriptor 忘了同步改成四 state，結果不可用；目前正在重跑正確的 `1,2,3,4` descriptor A/B，完成後才比較 recall。
- 正確的 split4 descriptor A/B 已完成：無 native/data error，validation loss `0.6425`，但 far recall `0/30`；對同一批 split4 訓練音訊轉成 3ch 後做 overfit，positive recall 仍為 `0/60`，negative false positive 為 0。這排除了單純 far-field 泛化問題，下一步必須提高正式訓練量並觀察收斂。
- 已啟動正式 split4 訓練 `work-3ch-split4-full50`：50 epochs、20 train batches/epoch、5 validation batches/epoch；目前進入 epoch 1，未見 native/data error。此輪完成後會自動接續 overfit、far ROC 與 threshold sweep。
- 已恢復訓練伺服器的 SSH key 登入；先前的密碼阻塞已解除，既有 full50 容器未被重啟。
- 截至 2026-09-30 18:01，full50 已完成 epoch 8/50，checkpoint 8 個；validation loss 由 epoch 1 的 `0.6250` 降至 epoch 8 的 `0.3074`。`Label index out of bounds`、音訊格式／輸入檔案錯誤與 traceback 計數均為 0。訓練容器仍在執行，需完成後再以同一 checkpoint 跑 overfit、normal、far 與 negative 評估。
- 已新增本地監控工具 `dev/features/kws_remote_monitor.sh`：每 60 秒以 SSH 查詢遠端容器，將結果寫入 `data/kws/monitor/full50.local.log`；目前本機 monitor 已啟動。`start/status/once/stop` 可控制與查詢，不依賴遠端 monitor log。
- 截至 2026-09-30 18:15，full50 已完成 epoch 17/50、checkpoint 17 個，validation loss `0.2323`，native/data error 仍為 0。
- 實測發現一般 `nohup` 背景程序會被工作階段清理回收，因此新增 `com.myagent.kws-monitor.plist` 並安裝為 macOS LaunchAgent；目前 launchd 狀態為 active，會每 60 秒執行本地 SSH poll。
- 截至 2026-09-30 18:45，full50 已完成 epoch 44/50、checkpoint 44 個，validation loss `0.1665`，native/data error 仍為 0；容器仍在執行。
- full50 已完成 50 epochs，產生 `first_txt/top_01_checkpoint_0050_loss_train_0.1864_loss_val_0.1607.txt`；訓練 log 中 native/data error 仍為 0。
- 完成的 top-1 checkpoint 評估結果：far positive `16/30 = 53.3%`、normal/train positive `10/30 = 33.3%`、ordinary negative false positive `0/10`。因此模型尚未達到正常距離 90%／遠距離 80% 門檻，不能進入 live shadow test；下一輪需先釐清訓練資料與 3ch evaluator 的訊號／標註對應，再增加資料或改 pipeline。
- 比對確認 alignment-derived overfit fixture 的 channel 0 與 training alignment 音訊逐 sample 完全一致；但 full50 top-1 在該 60 筆 overfit set 仍只有 `4/60 = 6.7%`，因此問題不是 far-field 泛化或 raw test 前後靜音單一因素。
- 嘗試把 noise lists 設為空列表時，官方 SoundConnect 在 validation 初始化階段 segmentation fault；改用合法的單一 16 kHz 靜音 noise fixture，啟動 `work-3ch-split4-clean20b`（20 epochs）作為 clean augmentation A/B。首個 epoch 正在執行，已確認無 native/data error。
- clean20b 已完成 20 epochs，loss_val `0.1019`、native/data error 為 0，但 far recall `0/30`，normal/train recall `0/30`；單純移除真實噪聲沒有改善，且低 loss 仍可能是 background-dominant collapse。
- 已啟動 `work-3ch-split4-cleanpos20`：正樣本保留、負樣本與所有 noise/ref/interference 改為合法靜音 fixture，作為正樣本記憶能力的最小 A/B；目前已進入 epoch 1，無 native/data error。
- cleanpos20 已完成 20 epochs，loss_val `0.0956`，但自動 far recall 仍為 `0/30`；正樣本-only／靜音負樣本仍無法讓 decoder 產生有效 wake sequence，已排除真實噪聲與普通負樣本是唯一根因。
- 三狀態 `1,2,3,3` + 原始 alignment A/B 很快重現 native `Label index out of bounds: ..., 3, 3`（停止前 51 次），因此已停止並保留 `repeat15.log`；三狀態 native 路徑目前判定不可用。
- 非連續 class `1,2,4` mapping 也重現 `3,3` warning（停止前 92 次），確認 SoundConnect 不接受以跳號避開 class 3 的方案；已停止並保留 `map124-10b.log`。
- 已啟動長訓練 `work-3ch-split4-full100`：連續四狀態 `1,2,3,4`、100 epochs、每 epoch 20 batches；截至 2026-09-30 21:13 已進入 epoch 1，native/data error 為 0。此輪不覆蓋 full50 或其他既有結果。
- 在 full100 執行期間建立第一批 macOS `say` 合成正樣本：原計畫 5 聲線 × 3 速率；實測 Eddy、Reed 對中文只產生約 16 ms 空音訊，已排除並保留於 `data/kws/tts/mac_say/unsupported/`，有效資料為 Meijia、Sinji、Tingting 共 9 筆。
- 9 筆有效 TTS 已轉為 16 kHz、16-bit、mono WAV，並傳至訓練伺服器；在官方 ModelScope Docker image 內以簡體描述符 `麦芽糖` 完成 force alignment，產生 9 個 stereo label WAV。這批只作低比例 augmentation，不會加入 full100，也不會替代真實 normal/far validation。
- TTS 資料策略：先以本機 `say` 建立可重現、無雲端依賴的 baseline；線上 TTS 或 Piper 只在確認服務憑證與逐聲線 license 後加入，並保留真實錄音作為唯一正式評估集。下一步待 full100 完成後，建立「real-only vs real+TTS」新訓練 A/B。
- 依照資料擴充需求，已排除香港／粵語 Sinji；本機 `say` 初步生成 8 個聲線、rate 120–220 每 5 一檔，但實際聽辨確認 Flo、Grandma、Grandpa、Rocko、Sandy、Shelley 都漏讀「麥」，因此將 126 個檔案移至 `unsupported/`。目前只保留 Meijia、Tingting，共 42 個有效 WAV；非空與格式檢查不能取代實際發音檢查。
- 透過 `edge-tts` 測試線上 TTS，選用 9 個 zh-CN／zh-TW 普通話聲線、慢速至加速 5 檔，共 45 個有效 WAV；只合成公開喚醒詞「麦芽糖」，未傳送私人文件。Edge TTS 產物暫作 augmentation 候選，仍需確認服務使用條款後才納入長期資料集。
- 原先 213 個新增 TTS WAV 已在遠端完成 alignment；經發音檢查後，126 個 macOS 不完整聲線的原始與 aligned 檔案均移至遠端 `data/kws/tts/unsupported/`，目前正式候選為 42 個 macOS WAV 加 45 個 Edge TTS WAV。full100 未修改，合成資料未放入 normal/far/negative 評估集。
- 截至 2026-09-30 21:51，`full100` 正在執行 epoch 38/100，epoch 37 validation loss `0.1672`，容器與訓練流程正常。過濾後的 87 個 TTS aligned WAV 可加入下一輪，但不直接全部混入；由於目前 real alignment 約 60 筆，下一輪先以受控比例建立 real-only vs real+TTS A/B，避免合成樣本數量主導訓練。
- 使用者已確認 45 個 Edge TTS 音檔發音正確，正式納入下一輪候選。遠端已準備 `positive_tts_container.txt`（87 筆）與 `positive_train_real_tts_container.txt`（60 筆 real + 87 筆 TTS，共 147 筆）；尚未啟動新訓練，等待 full100 完成後建立 A/B config。
- 最新狀態：截至 2026-09-30 22:09，`full100` 已完成 epoch 55/100、checkpoint 55 個；epoch 55 `loss_train=0.1602`、`loss_val=0.1429`，已開始 epoch 56，容器仍正常運行。
- 最新輪詢：截至 2026-09-30 22:22，`full100` 已完成 epoch 67/100、checkpoint 67 個；epoch 67 `loss_train=0.1480`、`loss_val=0.1344`，目前正在 epoch 68，容器仍正常運行。
- 最新輪詢：截至 2026-09-30 22:45，`full100` 已完成 epoch 89/100、checkpoint 89 個；epoch 89 `loss_train=0.1599`、`loss_val=0.1228`，目前正在 epoch 90，容器仍正常運行。
- `full100` 已完成 100 epochs 與 top-10 ROC 評估。validation 最佳 checkpoint 0100 在 threshold 0.15 下 normal `8/30=26.7%`、far `24/30=80%`、ordinary negative FP `0/10`；同批 top-08 checkpoint 在 normal `15/30=50%`、far `30/30=100%`，仍未達 normal 90% 產品門檻，因此不進 live。
- 已確認下一輪正式使用 147 筆正樣本：60 real + 42 個確認有效的 macOS `say` + 45 個確認有效的 Edge TTS；下一輪 config 將使用 `positive_train_real_tts_container.txt`，保留相同 normal/far/negative 評估集。
- 已啟動下一輪 `work-3ch-split4-real-tts100`，使用上述 147 筆 real+TTS positive manifest、相同 negative/noise 與 held-out 評估集；容器 `kws-real-tts100` 已成功進入 training，未見啟動錯誤。
- 首次 real+TTS 啟動後發現 TTS alignment 還是三狀態 `1/2/3`，觸發已知的 `Label index out of bounds ..., 3, 3`；已在 epoch 4 停止，保留 3 個 invalid checkpoint。現已將 87 個 TTS label 全部轉成 validated split4 `327/655/983/1310`，重建 147 筆 manifest 並重新啟動正確訓練；截至 2026-09-30 23:09 容器成功進入 model initialization。
- 最新狀態：修正後訓練已完成 epoch 35/100、checkpoint 35 個，epoch 35 `loss_train=0.1519`、`loss_val=0.1422`，目前進入 epoch 36；截至目前未再出現 label index 或音訊資料錯誤。
- 最新輪詢：截至 2026-10-01 00:01，修正後 real+TTS 訓練已完成 epoch 50/100、checkpoint 50 個；epoch 50 `loss_train=0.1314`、`loss_val=0.1330`，目前正在 epoch 51，未再出現 label/data error。
- 在不停止訓練的情況下，已單獨轉換並評估 checkpoint 0050：threshold `0.15` 時 far `29/30=96.7%`、normal `25/30=83.3%`、ordinary negative FP `0/10`；threshold `0.50` 時 far `30/30=100%`、normal `28/30=93.3%`，FP 仍為 0。這是目前最接近產品門檻的結果，但仍需等完整訓練與同一 threshold sweep 後決定。
- checkpoint 0050 評估期間原始訓練未中斷，最新已進入約 epoch 53，容器仍正常運行。
- 已將遠端 checkpoint 0050 的推理模型與 ModelScope runtime support files 複製至本機 `models/alibaba-kws-maiyatang-checkpoint50/`；本機 Python 3.10 worker 可成功載入，並將 `wake.toml` 暫時切換至 Alibaba provider，舊 Sherpa 設定保留於 `wake.sherpa.toml`。
- 本地 replay 目前結果：正樣本 `3/30=10%`、負樣本 `0/22=0%`。這與遠端官方 3ch ROC（normal 83.3%、far 96.7%、negative 0% at threshold 0.15）不一致，初步確認不是模型載入問題；下一步需對齊本機 mono→3ch worker 與官方 evaluator 的輸入／threshold 行為，再決定是否保留 production 切換。
- 2026-10-01：針對「退下後無法再次喚醒」補上 listener cycle boundary reset。每次 agent 由對話回到 wake-required standby、重新建立 microphone listener 時，會顯式 reset stateful KWS runtime（包含 Alibaba SoundConnect），並記錄 `wake_detector_reset reason=listener_started`；相關 listening 回歸測試已通過。用同一份 normalized positive WAV 實測 reset 前後連續兩輪均可命中 `0_mai_ya_tang`。
- 2026-10-01：實機仍未能在退下後再次喚醒，因此為隔離的 Alibaba KWS worker 加入 `data/logs/kws.log` 診斷記錄；保留最近 3000 行，記錄 worker ready、reset、每批 PCM/block、命中 confidence、health、shutdown 與 exception。另修正 `blocks` 欄位，使其代表實際處理的 block 數，而不是命中數。
- 2026-10-01：實機啟動時發現 Alibaba worker 載入 ModelScope 模型超過原本固定 5 秒 timeout，導致 `AlibabaKWSProcessError`。已將 worker response／初始化 timeout 提高到 20 秒；這只放寬啟動容錯，不改變音訊處理延遲。
- 2026-10-01：檢查實機首次喚醒失敗的 KWS log：worker、reset、PCM 接收與 block 推理均正常，但該次 live stream 沒有任何 hit，故目前排除 worker crash／reset 卡死，待加入 live PCM RMS／peak 後與 replay 輸入對照音量與裝置資料。
- 2026-10-01：按實驗要求暫時關閉 `wake.toml` 的 KWS normalization；本地 positive replay 為 `2/30=6.7%`，比開啟 normalization 時的 `3/30=10%` 略低，尚不能支持移除 normalization 會改善。待以 live `./start` 實測後再決定配置。
- 2026-10-01：檢查 Alibaba ModelScope 原始碼後確認推理狀態集中於 `SoundConnect`，官方沒有 reset API。已強化 reset：先釋放舊 native `SoundConnect`、執行 GC，再建立新的 `SoundConnect`，並記錄 reset 前後 `kwsState`；health 也回報 state／buffer。離線同一 positive WAV 連續三輪 `process → reset` 均命中，且 reset 後 `kwsState=0`，因此目前沒有證據顯示 reset 未回到初始狀態。
- 2026-10-01：新增 `dev/features/kws_reset_replay.py`，以同一個 detector 模擬兩輪 wake。使用真实录音执行「第一段 → reset → 第二段」：两轮均命中 `0_mai_ya_tang`，reset 前后 health 都是 `kws_state=0`、`buffered_bytes=0`；离线 reset 逻辑通过，问题需继续从 live 输入／模型召回率定位。
- 2026-10-01：新增 `dev/features/kws_reset_benchmark.py`，批量对 30 个 positive WAV 执行两轮 replay。关闭 normalization 下第一轮 `2/30=6.7%`、reset 后第二轮 `2/30=6.7%`、两轮都命中 `2/30`、first-only `0`、second-only `0`、reset state failure `0`；统计进一步确认 reset 没有导致二次召回下降。
- 2026-10-01：新增 `dev/features/stt_peak_compare.py`，使用当前 Qwen3-ASR 对同一 30 个 positive WAV 做 peak 1200／12000 对照。STT 正确识别「麦芽糖」：1200 为 `10/30=33.3%`，12000 为 `11/30=36.7%`；两者非常接近，12000 略优。初步不建议用单一 gain 同时绑死 KWS 与 STT，后续应评估多尺度训练增强，或让 KWS／STT 各自使用独立 preprocessing。
- 2026-10-01：按使用者决定建立单一 `normalized-12000` 训练资料集，共 486 个 WAV：60 real positive、240 mixed positive、19 negative、80 noise、87 已确认可用 TTS。原始资料未修改；新增 `dev/features/kws_prepare_normalized_dataset.py` 与各组 manifest／metadata。重新修正 int16 `-32768` peak overflow 后验证：非静音文件实际 peak 为 11999–12000，没有超过 12000。已试听 real、mixed、TTS 各一段。
- 2026-10-01：远端训练完成后单独检查 checkpoint 0099：官方 far positive 仅 `1/30=3.3%`，ordinary negative `0/10` false positive；ROC 文件标记 AUC 100%，但实际产品工作点 recall 很低，因此 checkpoint 0099 不能直接替换当前本地 KWS。下一步需先确认评估脚本／模型导出与训练 checkpoint 的对应关系，再决定是否把 normalized-12000 资料送去新一轮训练。
- 2026-10-01：以同一份官方 batch evaluator、同一 config、同一 30 筆 far positive／10 筆 ordinary negative 測試集，重新比較 checkpoint 0050 與 0099：兩者在 threshold `0.15` 都是 far `1/30=3.3%`、negative FP `0/10`。因此先前記錄的 checkpoint 0050 far `29/30=96.7%` 並不是這次同條件可重現的結果；它來自另一份既有 ROC／工作點產物，不能直接與本次結果混比。當前結論是：0099 沒有被證明優於 0050，兩者都不應直接作為 production KWS；下一步需先固定 evaluator 輸入、threshold、模型匯出與資料版本，再做可追溯的 checkpoint sweep。
- 2026-10-01：已將遠端 checkpoint 0099 的推理模型複製到本地 `models/alibaba-kws-maiyatang-checkpoint99/`，並保留 checkpoint 50 的完整 runtime 檔案作為基礎；`model.txt` SHA-256 為 `d98aa09813dd4a070e0d136247b76eaf1acd34b357a231948e942197c7f24005`。`AlibabaKWSDetector` 本地 worker 啟動與 health check 通過，`wake.toml` 已暫時切換至 0099，等待實機使用者測試。
- 2026-10-01：啟動 normalized-12000 A/B 訓練前，已將本地 486 筆資料上傳遠端；其中 387 筆 positive（60 real + 240 mixed + 87 TTS）完成官方 force alignment，另有 19 negative 與 80 noise。首次啟動因三狀態 alignment 觸發已知 `3,3` warning，已立即停止且未採用其 checkpoint；後續將 387 筆 label 轉為 validated split4（`327/655/983/1310`），並修正兩次 container manifest 路徑問題。
- 2026-10-01：normalized-12000 split4 訓練已用獨立 work dir `work-3ch-split4-normalized12000-split4b` 重新啟動；目前已完成 validation 初始化並進入 training，啟動階段 `Label index out of bounds` 與 `Cannot open input file` 均為 0。config 保存在 `dev/features/kws_normalized12000_config.yml`，待完成後再用固定 evaluator 比較 checkpoint。
