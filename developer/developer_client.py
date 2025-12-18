import asyncio
import json
import os
import sys
import zipfile
import tempfile
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.protocol import sendf, recvf
from shared.consts import DEV_PORT, DEFAULT_DEV_HOST

# --- Utils ---
async def ainput(prompt: str) -> str:
    print(prompt, end='', flush=True)
    return await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def pack_game(game_dir):
    game_path = Path(game_dir)
    if not game_path.exists():
        return None, 0, None
    
    cfg_path = game_path / "game_config.json"
    if not cfg_path.exists():
        print("Error: game_config.json missing in game directory.")
        return None, 0, None
        
    try:
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
    except:
        print("Error: Invalid game_config.json")
        return None, 0, None

    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(game_path):
            for file in files:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(game_path)
                zf.write(abs_path, rel_path)
    
    size = os.path.getsize(zip_path)
    return zip_path, size, config

# --- Flows ---

async def upload_game_flow(reader, writer, user):
    print("\n--- 上架/更新遊戲 ---")
    print("請輸入遊戲專案路徑 (例如 ./developer/games/demo_game):")
    path_str = (await ainput("> ")).strip()
    zip_path, size, config = pack_game(path_str)
    
    if not zip_path:
        print("打包失敗，請檢查路徑與設定檔")
        return

    print(f"打包成功: {size} bytes. Config: {config}")
    confirm = (await ainput("確認上傳? (y/n): ")).strip().lower()
    if confirm != 'y':
        os.remove(zip_path)
        return

    payload = {
        "type": "UPLOAD_INIT",
        "game_id": config.get("name").replace(" ", "_").lower(),
        "version": config.get("version"),
        "file_size": size,
        "metadata": config
    }
    await sendf(writer, payload)
    
    resp = await recvf(reader)
    if resp.get("status") != "READY_TO_RECV":
        print(f"Server 拒絕上傳: {resp.get('reason')}")
        os.remove(zip_path)
        return

    print("開始傳輸檔案...")
    with open(zip_path, "rb") as f:
        while True:
            chunk = f.read(64*1024)
            if not chunk: break
            writer.write(chunk)
            await writer.drain()
            
    resp = await recvf(reader)
    if resp.get("status") == "OK":
        print("上傳成功！")
    else:
        print(f"上傳失敗: {resp.get('reason')}")
        
    os.remove(zip_path)

async def view_reviews_flow(reader, writer, gid):
    await sendf(writer, {"type": "LIST_REVIEWS", "game_id": gid})
    resp = await recvf(reader)
    reviews = resp.get("reviews", [])
    print(f"\n--- {gid} 的評論 ({len(reviews)}) ---")
    if not reviews:
        print("(無評論)")
    for r in reviews:
        print(f"[{r['rating']}分] {r['user']}: {r['comment']}")
    input("\n按 Enter 返回...")

async def list_games_flow(reader, writer):
    await sendf(writer, {"type": "LIST_MY_GAMES"})
    resp = await recvf(reader)
    if resp.get("status") != "OK":
        print("無法取得列表")
        return
        
    games = resp.get("games", [])
    while True:
        print(f"\n--- 我的遊戲 ({len(games)}) ---")
        for i, g in enumerate(games):
            active = "上架中" if g.get("is_active") else "已下架"
            p_range = f"{g.get('min_players')}-{g.get('max_players')}"
            print(f"{i+1}. [{active}] {g['name']} (v{g['latest_version']}) | {g.get('type')} | {p_range}人 | ID:{g['id']}")
            desc = g.get('description', '')
            if desc: print(f"   說明: {desc}")
        
        print("\n操作: 輸入編號選擇遊戲 (0 返回)")
        idx_str = (await ainput("> ")).strip()
        if not idx_str.isdigit(): continue
        idx = int(idx_str)
        if idx == 0: break
        
        if 1 <= idx <= len(games):
            selected = games[idx-1]
            print(f"\n已選擇: {selected['name']}")
            print("1. 上架 (更新請直接使用主選單'上架/更新')")
            print("2. 下架")
            print("3. 查看評論")
            print("4. 取消")
            
            op = (await ainput("> ")).strip()
            if op == "1":
                print("請使用主選單的「1. 上架/更新遊戲」來重新上架/更新")
            elif op == "2":
                await sendf(writer, {"type": "OFFSHELF", "game_id": selected['id']})
                resp = await recvf(reader)
                print("操作結果:", resp.get("status"))
                selected['is_active'] = False 
            elif op == "3":
                await view_reviews_flow(reader, writer, selected['id'])
                
async def menu_loop(reader, writer, user):
    while True:
        print(f"\n=== 開發者選單 ({user}) ===")
        print("1. 上架/更新遊戲 (D1/D2)")
        print("2. 我的遊戲列表 (管理/下架 D3)")
        print("3. 登出")
        
        choice = (await ainput("> ")).strip()
        
        if choice == "1":
            await upload_game_flow(reader, writer, user)
        elif choice == "2":
            await list_games_flow(reader, writer)
        elif choice == "3":
            return
        else:
            print("無效選項")

async def auth_loop(reader, writer):
    while True:
        print("\n=== 開發者登入 ===")
        print("1. 登入")
        print("2. 註冊")
        print("3. 離開")
        choice = (await ainput("> ")).strip()
        
        if choice == "3": return None
        
        user = (await ainput("帳號: ")).strip()
        pwd = (await ainput("密碼: ")).strip()
        
        if choice == "1":
            await sendf(writer, {"type": "LOGIN", "user": user, "password": pwd})
            resp = await recvf(reader)
            if resp.get("status") == "OK":
                return resp.get("user")
            else:
                print(f"登入失敗: {resp.get('reason')}")
                
        elif choice == "2":
            await sendf(writer, {"type": "REGISTER", "user": user, "password": pwd})
            resp = await recvf(reader)
            if resp.get("status") == "OK":
                print("註冊成功，請登入")
            else:
                print(f"註冊失敗: {resp.get('reason')}")

async def main():
    try:
        reader, writer = await asyncio.open_connection(DEFAULT_DEV_HOST, DEV_PORT)
    except Exception as e:
        print(f"無法連線到開發者伺服器: {e}")
        return

    try:
        user = await auth_loop(reader, writer)
        if user:
            await menu_loop(reader, writer, user)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"發生錯誤: {e}")
    finally:
        writer.close()
        await writer.wait_closed()
        print("程式結束")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
