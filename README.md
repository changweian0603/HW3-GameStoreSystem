# 遊戲商城系統 (Game Store System)

這是一個基於 Python 實作的網路遊戲商城平台，包含伺服器端、開發者端與玩家端。
支援遊戲上架、版本管理、多人連線大廳、遊戲下載與即時對戰功能。

## 系統架構

專案分為三個主要模組：
1.  **Server (伺服器端)**:
    *   `DB Server` (Port 10001): 負責資料庫存取 (使用者data、遊戲metadata、評論)。
    *   `Lobby Server` (Port 11000): 負責玩家連線、大廳房間管理、協調遊戲啟動。
    *   `Dev Server` (Port 12000): 負責開發者連線、接收遊戲上傳檔案。
2.  **Developer (開發者端)**:
    *   提供 CLI 介面，讓開發者打包並上架/更新遊戲。
3.  **Player (玩家端)**:
    *   提供 CLI 介面，讓玩家瀏覽商城、下載遊戲、建立/加入房間並自動啟動遊戲客戶端。

## 快速開始

### 1. 啟動伺服器
請直接執行根目錄下的批次檔 (Windows):
```cmd
start_servers.bat
```
這會同時開啟三個視窗，分別執行 DB, Lobby, 和 Dev Server。

### 2. 開發者流程 (Developer Client)
**目標：上架您的遊戲供玩家下載。**
執行:
```cmd
python developer/developer_client.py
```
**操作流程**:
1.  **註冊/登入**: 初次使用請選擇 `2. 註冊`，之後使用 `1. 登入`。
2.  **上架遊戲**:
    *   選擇 `1. 上架/更新遊戲`。
    *   輸入遊戲專案路徑 (例如: `./developer/games/multi_clicker`)。
    *   系統會自動讀取 `game_config.json` 並打包上傳。
3.  **管理遊戲**:
    *   選擇 `2. 我的遊戲列表`。
    *   可查看已上架遊戲的狀態、版本，或進行下架操作。

### 3. 玩家流程 (Lobby Client)
**目標：下載遊戲並與其他玩家連線對戰。**
執行:
```cmd
python player/lobby_client.py
```
**操作流程**:
1.  **註冊/登入**: 玩家與開發者帳號獨立，初次使用請註冊。
2.  **遊戲商城**:
    *   選擇 `1. 遊戲商城` -> `1. 瀏覽/下載遊戲`。
    *   列表顯示遊戲 ID、名稱、類型、支援人數與作者資訊。
    *   選擇遊戲並下載 (檔案會存放於 `player/downloads/{username}/{game_id}`)。
3.  **遊戲大廳 (多人連線)**:
    *   選擇 `2. 遊戲大廳`。
    *   **建立房間**: 選擇 `3. 建立房間`，挑選已下載的遊戲。您將成為房主 (Host)。
    *   **加入房間**: 選擇 `2. 瀏覽/加入房間`，查看線上房間列表並加入。
    *   **等待室**: 當所有玩家準備就緒，房主選擇 `2. 開始遊戲`。
    *   **遊戲啟動**: 系統會自動呼叫所有玩家電腦上的遊戲客戶端 (GUI 或 CLI) 進行連線。
4.  **遊戲結束**:
    *   關閉遊戲視窗後，回到 CLI 介面。
    *   系統會詢問是否給予評分與評論。

## 內建遊戲介紹

本專案附帶三個範例遊戲，位於 `developer/games/` 目錄下：

1.  **GUI Tetris (俄羅斯方塊)**
    *   **路徑**: `developer/games/gui_tetris`
    *   **類型**: GUI / 雙人對戰
    *   **說明**: 使用 Tkinter 繪製。兩位玩家同時進行遊戲，比拼消除行數或是生存時間。
    *   **操作**: 方向鍵移動/變形，空白鍵丟下。

2.  **Multi Clicker (多人點擊競賽)**
    *   **路徑**: `developer/games/multi_clicker`
    *   **類型**: GUI / 多人 (3-5人)
    *   **說明**: 適合多人同樂的簡單遊戲。所有玩家視窗同步顯示分數板，最快點擊按鈕達到 50 次者獲勝。

3.  **CLI RPS (猜拳遊戲)**
    *   **路徑**: `developer/games/cli_rps`
    *   **類型**: CLI / 雙人對戰
    *   **說明**: 在終端機執行的剪刀石頭布。展示了如何在沒有圖形介面的情況下實作即時對戰。

## 專案檔案清單 (File List)

執行本專案所需的原始檔案如下 (不包含 `__pycache__`, `storage/`, `downloads/` 等執行時生成的目錄)：

```text
hw3/
├── start_servers.bat           # 伺服器啟動腳本
├── README.txt                  # 專案說明文件
├── VERIFICATION_GUIDE.md       # 詳細驗證步驟
│
├── server/                     # 伺服器端程式碼
│   ├── db_server.py            # 資料庫伺服器
│   ├── dev_server.py           # 開發者伺服器
│   └── lobby_server.py         # 大廳伺服器
│
├── shared/                     # 共用模組
│   ├── __init__.py
│   ├── consts.py               # 常數定義 (Ports, Hosts)
│   └── protocol.py             # 通訊協定 (sendf, recvf)
│
├── developer/                  # 開發者端
│   ├── developer_client.py     # 開發者客戶端主程式
│   │
│   └── games/                  # 範例遊戲原始碼
│       ├── gui_tetris/
│       │   ├── client.py
│       │   ├── server.py
│       │   └── game_config.json
│       ├── multi_clicker/
│       │   ├── client.py
│       │   ├── server.py
│       │   └── game_config.json
│       └── cli_rps/
│           ├── client.py
│           ├── server.py
│           └── game_config.json
│
└── player/                     # 玩家端
    └── lobby_client.py         # 玩家客戶端主程式
```

## 開發資訊
*   **語言**: Python 3.8+
*   **通訊**: TCP Socket (Asyncio) + JSON
*   **GUI**: Tkinter (內建於 Python)
*   **相容性**: Windows (測試環境), Linux/macOS (理論相容，需自行處理路徑與啟動腳本)
