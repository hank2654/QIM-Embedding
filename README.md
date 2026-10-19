# QIM-Embedding

使用 Python 對 STEP/STP 的每個 **`VERTEX_POINT` 拓撲頂點**嵌入 1 bit：量化頂點到固定模型中心的距離，沿原方向調整座標，再輸出 STP。另一支程式直接讀取輸出 STP 的座標，還原每個頂點的 bit。

支援自訂量化間距、全部藏 0、全部藏 1、隨機 bits，以及逐頂點指定。核心程式只需 **Python 3.10+，無第三方依賴**，可在 Windows、macOS、Linux 的 VS Code 終端執行。

## 先了解幾何限制

這是**頂點座標 QIM 實驗工具**。任意移動 B-rep 頂點，會影響它與原有邊、曲面的吻合；程式不重建曲線或曲面，不能保證輸出仍適合 CAD 編輯、製造或分析。檔案中的其他幾何實體會保留，也不會把曲面控制點當成要嵌入的頂點。每個頂點會參照一個新的 `CARTESIAN_POINT`，避免共用點導致不同 bits 互相覆蓋。

你提供的 `examples/2.stp` 含 216 個 `VERTEX_POINT`；示範輸出在原始 STEP 座標層級可完整還原 216 bits。OpenCascade 匯入原檔與示範輸出皆成功，匯入後的 B-rep 檢查皆為有效；匯入器可能修復幾何，因此這不代表任意參數均有效，也不代表經 CAD 另存後仍能保留 bits。匯入後 OpenCascade 產生 227 個頂點，與原始檔案的 216 個實體不同，兩者計數不可混用。

目前支援單一座標系的 3D `VERTEX_POINT → CARTESIAN_POINT` STEP。偵測到常見組件 placement/mapping 會拒絕處理；不支援一般組立件的世界座標變換。純 tessellated STEP、沒有 `VERTEX_POINT` 的檔案亦不支援。

## 在 VS Code 開啟

1. 用 VS Code 開啟此 repository 資料夾，安裝建議的 Python 與 Python Debugger 擴充套件。
2. 選擇 Python 3.10 以上的解譯器。
3. 開啟「執行與偵錯」，選擇 **QIM: Embed 2.stp (216 bits)**，按 F5。畫面會詢問 `delta`、bit 模式與隨機 seed。
4. 再選 **QIM: Extract from 2.qim.stp**，按 F5，終端會顯示還原的 bit 字串。

F5 設定使用 `--overwrite`，會更新範例輸出與報告。也可以在終端使用以下指令；工作目錄皆為 repository 根目錄。Windows 若沒有 `python3` 指令，改用 `python`。

## 嵌入與擷取

```bash
# 隨機嵌入；相同 seed 在相同頂點順序下可重現
python3 embed_step.py examples/2.stp examples/2.qim.stp --delta 0.01 --mode random --seed 42 --report examples/2.embed.json --overwrite

# 從輸出 STP 的座標擷取，不讀取嵌入報告或原始檔
python3 extract_step.py examples/2.qim.stp --output examples/2.extracted.json --overwrite
```

`--report` 是選填，用於比較原始 bits、逐頂點位移、原始／輸出座標與 SHA-256。擷取程式不需要這份報告。輸出 STP 的 `QIM_RADIAL_V1` 註解只保存量化間距、固定中心及頂點 ID，不保存 bits 或 seed。

輸出檔若已存在，預設會拒絕覆寫，需明確加上 `--overwrite`。即使加上此旗標，也不可把輸出路徑設為輸入原始檔。以下範例會寫入新的檔名。

```bash
# 每個頂點全部藏 0
python3 embed_step.py examples/2.stp examples/all_zero.stp --delta 0.01 --mode 0

# 每個頂點全部藏 1
python3 embed_step.py examples/2.stp examples/all_one.stp --delta 0.01 --mode 1

# 依序給完整 bit 字串（長度必須等於頂點數；此例適用於 4 頂點模型）
python3 embed_step.py four_vertices.stp marked.stp --delta 0.01 --bits 0101

# 逐頂點指定；未指定的頂點依 --mode 處理
python3 embed_step.py examples/2.stp examples/custom.stp --delta 0.01 --mode random --seed 42 --bits-file examples/vertex_bits.json

# 將擷取結果另外存成純 bit 字串
python3 extract_step.py examples/custom.stp --bits-output examples/custom.bits.txt
```

逐頂點設定檔 `examples/vertex_bits.json` 的格式如下：key 是 STP 中的 **`VERTEX_POINT` 實體 ID**，可有或沒有 `#`，不是 `CARTESIAN_POINT` ID，也不是從 0 開始的陣列索引。值可以是整數 `0`、整數 `1` 或字串 `"random"`。未知、重複或不合法的 ID 會報錯。

```json
{
  "1556": 0,
  "1557": 1,
  "1558": "random"
}
```

`--bits` 與報告中的 bit 字串都按 `VERTEX_POINT` 的數值 ID 由小到大排列；重合但 ID 不同的頂點分別藏 bit。可先查詢任意檔案的頂點清單與中心：

```bash
python3 inspect_step.py examples/2.stp --output examples/vertices.json
```

## QIM 定義與量化間距

模型中心預設為**原始拓撲頂點座標的算術平均**，不是體積質心或 bounding box 中心。亦可用 `--center X Y Z` 自訂中心。

對頂點 `v`、固定中心 `c`，計算 `r = ||v-c||₂`。本專案將 `Δ = --delta` 定義為相鄰量化格點的距離，同一 bit 的格點間距為 `2Δ`：

| bit | 半徑的可選格點 |
| --- | --- |
| 0 | `0, 2Δ, 4Δ, 6Δ, …` |
| 1 | `Δ, 3Δ, 5Δ, 7Δ, …` |

選取對應 bit 的最近非負格點 `r'`，等距時取較大的半徑，再令 `v' = c + (v-c) × r'/r`。擷取時計算 `floor(||v'-c||₂/Δ + 0.5) % 2`。

- `Δ` 必須大於 0，單位跟 STP 原始座標一致。此範例為 mm，因此 `0.01` 代表 0.01 mm。
- 單一頂點理論位移最多為 `Δ`，浮點運算有微小誤差。`Δ` 太大可能造成頂點重合或幾何退化；太小則可能無法可靠地用浮點數儲存，程式會檢查序列化後是否仍可還原。
- 若頂點恰好位於中心，bit 0 保持在中心，bit 1 沿固定的 +X 方向移動 `Δ`。
- **擷取時必須使用原始固定中心**。嵌入後頂點平均座標通常會改變，重新計算中心會破壞解碼。
- 距離量化邊界的理想裕度為 `Δ/2`；這不是任意幾何攻擊、重存、平移、縮放或頂點重新排序後的可靠性保證。本工具未包含加密、同步碼或錯誤更正碼。

若註解遭移除，但頂點座標與順序保持不變，可自行提供原本的參數。此範例中心如下：

```bash
python3 extract_step.py examples/2.qim.stp --delta 0.01 --center -3.458595284111294 -3.6706706830507105 -22.42417540538089
```

擷取結果中的 `lattice_error_in_delta` 是半徑到最近格點的距離除以 `Δ`。大於 `1e-6` 時標記為 off-lattice，仍輸出最近格點估計的 bits，但回傳退出碼 `1`；正常解碼為 `0`，參數／檔案錯誤為 `2`。落在格點上也不能單憑此判定 bit 未被翻轉，需要與原始 payload 或錯誤更正碼比較。

## 驗證

```bash
python3 -m unittest discover -s tests -v
```

測試涵蓋 QIM 格點、兩個頂點共用座標點時的獨立 bits、零半徑、固定中心、CRLF、STEP 註解與字串、重複嵌入、檔案保護、參數錯誤、CLI 往返，以及你的 216 頂點模型在 3 種模式 × 4 種 `Δ`（0.001、0.01、0.1、1.0）下的還原。

選用的 CAD 檢查需要 OpenCascade，核心嵌入／擷取程式不需要安裝：

```bash
python3 -m venv .venv
# macOS / Linux
.venv/bin/python -m pip install -r requirements-cad.txt
.venv/bin/python check_step_geometry.py examples/2.stp examples/2.qim.stp
# Windows 對應解譯器路徑：.venv\Scripts\python.exe
```

`check_step_geometry.py` 分別確認 STEP 可讀、能轉成 shape、以及匯入後的 `BRepCheck_Analyzer` 結果。所有檔案有效時退出碼為 `0`，有無效 B-rep 時為 `1`，缺依賴或讀取失敗時為 `2`。範例檢查結果存於 `examples/geometry_check.json`。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `embed_step.py` | 嵌入 bits 並輸出 STP |
| `extract_step.py` | 從 STP 座標擷取 bits |
| `qim_step.py` | STEP 實體讀寫與 QIM 核心 |
| `inspect_step.py` | 查詢頂點 ID、座標與半徑 |
| `check_step_geometry.py` | 選用 OpenCascade 幾何檢查 |
| `.vscode/launch.json` | VS Code F5 設定 |
| `examples/2.stp` | 使用者提供的原始檔 |
| `examples/2.qim.stp` | `Δ=0.01`、random seed 42 的輸出檔 |
| `examples/2.embed.json` / `2.extracted.json` | 原始 payload／位移報告與獨立擷取報告 |
