import asyncio
import json
import os
import sys
import subprocess
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.protocol import sendf, recvf
from shared.consts import LOBBY_PORT, DEFAULT_LOBBY_HOST, DOWNLOADS_DIR

# --- Globals ---
USER = None
DOWNLOADS_ROOT = Path(__file__).parent / DOWNLOADS_DIR

# --- Utils ---
async def ainput(prompt: str) -> str:
    print(prompt, end='', flush=True)
    return await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)

def check_game_installed(game_id, version):
    gpath = DOWNLOADS_ROOT / USER / game_id
    cpath = gpath / "game_config.json"
    if not cpath.exists(): return False, None
    try:
        cfg = json.loads(cpath.read_text(encoding="utf-8"))
        local_ver = cfg.get("version")
        return (local_ver == version), local_ver
    except: return False, None

def get_installed_games():
    games = []
    user_root = DOWNLOADS_ROOT / USER
    if not user_root.exists(): return []
    for d in user_root.iterdir():
        if d.is_dir():
            params = check_game_installed(d.name, None)
            if params[1]: games.append({"id": d.name, "version": params[1]})
    return games

# --- Sub Flows ---

async def view_reviews(reader, writer, game_id):
    await sendf(writer, {"type": "LIST_REVIEWS", "game_id": game_id})
    resp = await recvf(reader)
    if resp.get("status") == "OK":
        reviews = resp.get("reviews", [])
        print(f"\n--- {game_id} 評論 ({len(reviews)}) ---")
        if not reviews: print("(無評論)")
        for r in reviews:
            print(f"[{r['rating']}分] {r['user']}: {r['comment']}")
    else:
        print("無法取得評論")
    input("\n按 Enter 返回...")

async def waiting_room_loop(reader, writer, room_info, is_host):
    # room_info: {room_id, port, token, game_id, ...}
    rid = room_info["room_id"]
    gid = room_info.get("game_id", "(Unknown)")
    
    print(f"\n進入房間 {rid} (Game: {gid})...")
    
    while True:
        await sendf(writer, {"type": "ROOM_STATUS", "room_id": rid})
        resp = await recvf(reader)
        
        if resp.get("status") != "OK":
            print(f"無法取得房間狀態 (可能已解散): {resp.get('reason')}")
            break
            
        status = resp.get("room_status")
        players = resp.get("players", [])
        min_p = resp.get("min_players", 1)
        
        print(f"\n--- 房間等待室 ({status}) ---")
        print(f"玩家 ({len(players)}/{min_p}+): {', '.join(players)}")
        
        if status == "PLAYING":
            print("遊戲已開始！正在啟動客戶端...")
            await launch_game(room_info, DOWNLOADS_ROOT / USER / gid)
            break
            
        print("1. 重整狀態")
        if is_host:
            print("2. 開始遊戲 (Start Game)")
        print("3. 離開房間")
        
        op = (await ainput("> ")).strip()
        
        if op == "1":
            continue
        elif op == "2" and is_host:
            if len(players) < min_p:
                print(f"人數不足，需要至少 {min_p} 人")
                continue
            await sendf(writer, {"type": "START_GAME", "room_id": rid})
            s_resp = await recvf(reader)
            if s_resp.get("status") == "OK":
                print("啟動中...")
            else:
                print(f"啟動失敗: {s_resp.get('reason')}")
                
        elif op == "3":
            await sendf(writer, {"type": "LEAVE_ROOM", "room_id": rid})
            await recvf(reader)
            break

async def launch_game(info, game_path):
    cfg_path = game_path / "game_config.json"
    try:
        cfg = json.loads(cfg_path.read_text())
        cmd_tmpl = cfg.get("run_cmd", [])
        if not cmd_tmpl: raise ValueError("No run_cmd")
        
        cmd = list(cmd_tmpl)
        cmd.extend([
            "--host", info["host"], 
            "--port", str(info["port"]), 
            "--token", info["token"], 
            "--room-id", info["room_id"]
        ])
        
        print(f"Executing: {cmd}")
        subprocess.run(cmd, cwd=str(game_path))
        print("遊戲結束")
        await review_flow(info.get("game_id"))
        
    except Exception as e:
        print(f"啟動遊戲失敗: {e}")

global_writer = None
global_reader = None

async def review_flow(game_id):
    if not game_id: return
    print("\n--- 遊戲結束評價 (P4) ---")
    c = (await ainput("是否要給予評價? (y/n): ")).strip().lower()
    if c != 'y': return
    
    rating = (await ainput("評分 (1-5): ")).strip()
    comment = (await ainput("評論: ")).strip()
    
    await sendf(global_writer, {
        "type": "SUBMIT_REVIEW", 
        "game_id": game_id, 
        "rating": rating, 
        "comment": comment
    })
    resp = await recvf(global_reader)
    if resp.get("status") == "OK":
        print("評價送出成功！")
    else:
        print(f"評價失敗: {resp.get('reason')}")

# --- Main Menus ---

async def download_game(reader, writer, game_id):
    await sendf(writer, {"type": "DOWNLOAD_GAME", "game_id": game_id})
    resp = await recvf(reader)
    if resp.get("status") != "OK":
        print(f"下載失敗: {resp.get('reason')}")
        return False
    
    size = resp.get("size")
    version = resp.get("version")
    print(f"下載中: {game_id} (v{version}), Size: {size}")
    
    tmp_dir = DOWNLOADS_ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / f"{game_id}.part"
    
    read_bytes = 0
    with open(tmp_file, "wb") as f:
        while read_bytes < size:
            chunk = await reader.readexactly(min(64*1024, size - read_bytes))
            f.write(chunk)
            read_bytes += len(chunk)
            print(f"\r{(read_bytes/size)*100:.1f}%", end='')
    
    target_dir = DOWNLOADS_ROOT / USER / game_id
    if target_dir.exists():
        import shutil
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    import zipfile
    with zipfile.ZipFile(tmp_file, 'r') as zf:
        zf.extractall(target_dir)
    os.remove(tmp_file)
    print("\n安裝成功！")
    return True

async def store_menu(reader, writer):
    cached_games = []
    while True:
        print("\n--- 遊戲商城 ---")
        print("1. 瀏覽/下載遊戲")
        print("2. 返回")
        
        c = (await ainput("> ")).strip()
        if c == "1":
            await sendf(writer, {"type": "LIST_GAMES"})
            resp = await recvf(reader)
            cached_games = resp.get("games", [])
            
            print(f"\n{'No.':<4} {'ID':<15} {'名稱':<15} {'類型':<6} {'人數':<5} {'作者':<10} {'評分':<8}")
            print("-" * 85)
            if not cached_games:
                print("目前沒有可遊玩的遊戲")
            for i, g in enumerate(cached_games):
                rating_str = f"{g.get('rating_avg', 0):.1f}"
                p_range = f"{g.get('min_players')}-{g.get('max_players')}"
                print(f"{i+1:<4} {g['id']:<15} {g['name']:<15} {g.get('type','?'):<6} {p_range:<5} {g.get('author','?'):<10} {rating_str:<8}")
                desc = g.get('description', '')
                if desc: print(f"       說明: {desc}")
            
            print("\n輸入編號選擇 (0 返回):")
            idx = int((await ainput("> ")).strip() or 0)
            if idx == 0: continue
            
            if 1 <= idx <= len(cached_games):
                sel = cached_games[idx-1]
                print(f"已選擇: {sel['name']}")
                print("1. 下載/更新")
                print("2. 查看評論")
                print("3. 取消")
                op = (await ainput("> ")).strip()
                
                if op == "1": await download_game(reader, writer, sel['id'])
                elif op == "2": await view_reviews(reader, writer, sel['id'])
        
        elif c == "2": break

async def lobby_menu(reader, writer):
    while True:
        print("\n--- 遊戲大廳 ---")
        print("1. 線上狀態 (P3)")
        print("2. 瀏覽/加入房間")
        print("3. 建立房間")
        print("4. 返回")
        
        c = (await ainput("> ")).strip()
        
        if c == "1":
            await sendf(writer, {"type": "LIST_ONLINE"})
            resp = await recvf(reader)
            print("\n線上玩家:")
            for u in resp.get("users", []):
                print(f"- {u['name']} ({u['status']})")
        
        elif c == "2":
            await sendf(writer, {"type": "LIST_ONLINE"})
            resp = await recvf(reader)
            rooms = resp.get("rooms", [])
            print("\n房間列表:")
            for i, r in enumerate(rooms):
                print(f"{i+1}. {r['game_id']} | Host: {r['host']} | Players: {r['players']} | Status: {r['status']}")
            
            print("\n輸入編號加入 (0 返回):")
            idx = int((await ainput("> ")).strip() or 0)
            if idx > 0 and idx <= len(rooms):
                target = rooms[idx-1]
                gid = target['game_id']
                matches, local_ver = check_game_installed(gid, None)
                
                if not local_ver:
                    print(f"請先下載 {gid}")
                    continue
                
                await sendf(writer, {"type": "JOIN_ROOM", "room_id": target['id'], "game_version": local_ver})
                resp = await recvf(reader)
                if resp.get("status") == "OK":
                    resp["game_id"] = gid 
                    await waiting_room_loop(reader, writer, resp, is_host=False)
                else:
                    print(f"加入失敗: {resp.get('reason')}")

        elif c == "3":
            my_games = get_installed_games()
            print("\n選擇遊玩:")
            for i, g in enumerate(my_games):
                print(f"{i+1}. {g['id']} (v{g['version']})")
            
            idx = int((await ainput("> ")).strip() or 0)
            if idx > 0 and idx <= len(my_games):
                sel = my_games[idx-1]
                await sendf(writer, {"type": "CREATE_ROOM", "game_id": sel['id'], "game_version": sel['version']})
                resp = await recvf(reader)
                if resp.get("status") == "OK":
                    resp["game_id"] = sel['id']
                    await waiting_room_loop(reader, writer, resp, is_host=True)
                else:
                     print(f"建立失敗: {resp.get('reason')}")
        
        elif c == "4": break

async def my_games_menu():
    while True:
        games = get_installed_games()
        print(f"\n--- 我的遊戲 ({len(games)}) ---")
        for i, g in enumerate(games):
            print(f"{i+1}. {g['id']} (v{g['version']})")
        print("0. 返回")
        if (await ainput("> ")).strip() == "0": break

async def auth_loop(reader, writer):
    while True:
        print("\n=== 玩家登入 ===")
        print("1. 登入")
        print("2. 註冊")
        print("3. 離開")
        c = (await ainput("> ")).strip()
        if c == "3": return None
        
        u = (await ainput("User: ")).strip()
        p = (await ainput("Pass: ")).strip()
        
        if c == "1":
            await sendf(writer, {"type": "LOGIN", "user": u, "password": p})
            resp = await recvf(reader)
            if resp.get("status") == "OK": return resp.get("user")
            else: print(f"登入失敗: {resp.get('reason')}")
        elif c == "2":
            await sendf(writer, {"type": "REGISTER", "user": u, "password": p})
            resp = await recvf(reader)
            print("註冊成功" if resp.get("status") == "OK" else f"註冊失敗: {resp.get('reason')}")

async def main():
    global USER, global_reader, global_writer
    try:
        reader, writer = await asyncio.open_connection(DEFAULT_LOBBY_HOST, LOBBY_PORT)
        global_reader = reader
        global_writer = writer
    except:
        print("無法連線大廳")
        return

    try:
        USER = await auth_loop(reader, writer)
        if USER:
            while True:
                print(f"\n=== 玩家主選單 ({USER}) ===")
                print("1. 遊戲商城")
                print("2. 遊戲大廳")
                print("3. 我的遊戲")
                print("4. 登出")
                c = (await ainput("> ")).strip()
                if c == "1": await store_menu(reader, writer)
                elif c == "2": await lobby_menu(reader, writer)
                elif c == "3": await my_games_menu()
                elif c == "4": break
    except KeyboardInterrupt: pass
    finally:
        writer.close()
        await writer.wait_closed()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
