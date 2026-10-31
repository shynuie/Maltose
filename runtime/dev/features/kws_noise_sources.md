# KWS 環境負樣本來源清單

## 使用規則

- 網路音檔先放在 `data/kws/external/`，不可直接覆蓋原始錄音。
- 每個檔案必須保存來源 URL、作者、license、下載日期與 checksum。
- CC0 可作為 training augmentation；CC-BY 必須保留 attribution；CC-BY-NC 與限制商用的素材只作本地 research/stress test。
- 未確認授權的 YouTube、Podcast、電影或音樂，不納入可分發的 training/test dataset。
- 外部素材以 training augmentation 和 stress test 為主；正式 test set 應保留未參與調參的素材。

## 優先來源

| 來源 | 適合內容 | 用途 | 注意事項 |
|---|---|---|---|
| [MUSAN](https://www.openslr.org/17/) | speech、music、noise | 混音 augmentation、VAD/KWS stress test | 保存原始資料與版本資訊 |
| [Freesound](https://freesound.org/) | 鍵盤、風扇、家電、交通、室內 ambience | CC0 training augmentation；CC-BY research | 每段逐一確認 license 與作者，不使用未標記授權的檔案 |
| [BBC Sound Effects](https://sound-effects.bbcrewind.co.uk/) | 大量自然與場景聲 | 個人／教育／研究 stress test | 一般免費條件不等於商業授權；商業用途需另行授權 |

## 已下載資料

### ESC-50

- 來源：<https://github.com/karolpiczak/ESC-50>
- 本地位置：`data/kws/external/esc50/ESC-50-master/`
- 內容：2,000 段、50 類環境聲，每段約 5 秒
- License：CC BY-NC；目前只作內部研究與 stress test，不作商業模型或可分發資料
- 原始 metadata：`meta/esc50.csv`
- 目前不把完整資料集納入 replay；先挑選 `keyboard_typing`、`mouse_click`、`vacuum_cleaner`、`washing_machine`、`wind`、`rain`、`engine`、`door_wood_knock` 等類別，轉檔後再建立 external manifest。

## 目標場景

- 辦公桌：鍵盤、滑鼠、桌面敲擊、電腦風扇
- 家庭：空調、除濕機、吸塵器、洗衣機、廚房聲
- 播放聲：電視、音樂、Podcast、手機通知音
- 戶外：街道、車流、雨聲、人群、施工
- 語音干擾：其他人說話、遠處對話、電台／廣播

## 匯入前檢查

1. 轉成 16kHz、mono、16-bit PCM 的衍生檔，保留原始檔。
2. 記錄 duration、RMS、peak、source、license、attribution 與場景標籤。
3. 不把包含「麥芽糖」完整字串的語音素材標成 negative。
4. 先以 `myagent-kws-replay` 檢查 baseline 誤觸發，再決定是否加入 benchmark。
