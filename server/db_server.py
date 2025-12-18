import asyncio
import json
import os
import pathlib
import sys
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.protocol import sendf, recvf
from shared.consts import DB_PORT

DB_FILE = pathlib.Path("db.json")
DB_LOCK = asyncio.Lock()

DB = {
    "users_dev": {},    # { username: {pwd, games: []} }
    "users_player": {}, # { username: {pwd, status, play_history: []} }
    "games": {},        # { game_id: { ... } }
    "rooms": {},        # { room_id: { ... } }
    "reviews": {},      # { review_id: { ... } }
    "_counters": {
        "room": 0,
        "review": 0
    }
}

def load_db():
    global DB
    if DB_FILE.exists():
        try:
            content = DB_FILE.read_text(encoding="utf-8")
            if content.strip():
                DB = json.loads(content)
                for key in ["users_dev", "users_player", "games", "rooms", "reviews", "_counters"]:
                    if key not in DB:
                        DB[key] = {} if key != "_counters" else {"room": 0, "review": 0}
                print("[DB] Database loaded successfully.")
            else:
                print("[DB] db.json is empty, initializing new DB.")
                atomic_save()
        except Exception as e:
            print(f"[DB] Error loading DB: {e}. Using empty DB.")
    else:
        print("[DB] db.json not found, creating new.")
        atomic_save()

def atomic_save():
    """
    Save DB to disk atomically to prevent corruption on crash.
    Write to .tmp first, then rename.
    """
    tmp_file = DB_FILE.with_suffix(".tmp")
    try:
        data = json.dumps(DB, ensure_ascii=False, indent=2)
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno()) 
        os.replace(tmp_file, DB_FILE)
    except Exception as e:
        print(f"[DB] Save failed: {e}")

# --- Helper Functions ---

def get_next_id(kind):
    DB["_counters"].setdefault(kind, 0)
    DB["_counters"][kind] += 1
    return str(DB["_counters"][kind])

# --- Handlers ---

def handle_user_dev_register(data):
    user = data.get("user")
    pwd = data.get("password")
    if user in DB["users_dev"]:
        return {"ok": False, "reason": "ACCOUNT_EXISTS"}
    
    DB["users_dev"][user] = {
        "password": pwd,
        "games": [],
        "created_at": get_next_id("timestamp")
    }
    atomic_save()
    return {"ok": True}

def handle_user_dev_auth(data):
    user = data.get("user")
    pwd = data.get("password")
    u = DB["users_dev"].get(user)
    if not u:
        return {"ok": False, "reason": "USER_NOT_FOUND"}
    if u["password"] != pwd:
        return {"ok": False, "reason": "WRONG_PASSWORD"}
    return {"ok": True}

def handle_user_player_register(data):
    user = data.get("user")
    pwd = data.get("password")
    if user in DB["users_player"]:
        return {"ok": False, "reason": "ACCOUNT_EXISTS"}
    
    DB["users_player"][user] = {
        "password": pwd,
        "status": "Idle",
        "play_history": [],
        "created_at": get_next_id("timestamp")
    }
    atomic_save()
    return {"ok": True}

def handle_user_player_auth(data):
    user = data.get("user")
    pwd = data.get("password")
    u = DB["users_player"].get(user)
    if not u:
        return {"ok": False, "reason": "USER_NOT_FOUND"}
    if u["password"] != pwd:
        return {"ok": False, "reason": "WRONG_PASSWORD"}
    return {"ok": True, "play_history": u.get("play_history", [])}

def handle_game_upload(data):
    gid = data.get("game_id")
    meta = data.get("metadata")
    v_info = data.get("version_info")

    if gid not in DB["games"]:
        DB["games"][gid] = {
            "id": gid,
            **meta,
            "versions": [],
            "reviews": [],
            "rating_sum": 0,
            "rating_count": 0,
            "is_active": True
        }
    else:
        for k, v in meta.items():
            DB["games"][gid][k] = v
        
        DB["games"][gid]["is_active"] = True
            
    if v_info:
        DB["games"][gid]["versions"].append(v_info)
        DB["games"][gid]["latest_version"] = v_info["version"]
        
    atomic_save()
    return {"ok": True}

def handle_game_list(data):
    include_inactive = data.get("include_inactive", False)
    games = []
    for gid, g in DB["games"].items():
        if include_inactive or g.get("is_active", True):
            games.append({
                "id": g["id"],
                "name": g["name"],
                "author": g.get("author", "unknown"),
                "latest_version": g["latest_version"],
                "description": g.get("description", ""),
                "rating_avg": g.get("average_rating", 0),
                "rating_count": g.get("rating_count", 0),
                "is_active": g.get("is_active", True),
                "type": g.get("type", "Unknown"),
                "min_players": g.get("min_players", 1),
                "max_players": g.get("max_players", 2)
            })
    return {"ok": True, "games": games}

def handle_game_update_status(data):
    gid = data.get("game_id")
    active = data.get("is_active")
    if gid in DB["games"]:
        DB["games"][gid]["is_active"] = active
        atomic_save()
        return {"ok": True}
    return {"ok": False, "reason": "NOT_FOUND"}

def handle_record_play(data):
    user = data.get("user")
    gid = data.get("game_id")
    if user in DB["users_player"]:
        ph = DB["users_player"][user].setdefault("play_history", [])
        if gid not in ph:
            ph.append(gid)
            atomic_save()
    return {"ok": True}

def handle_submit_review(data):
    # {game_id, user, rating, comment}
    gid = data.get("game_id")
    user = data.get("user")
    rating = int(data.get("rating"))
    comment = data.get("comment")
    
    u = DB["users_player"].get(user)
    if not u or gid not in u.get("play_history", []):
        return {"ok": False, "reason": "MUST_PLAY_FIRST"}
    
    for rid, r in DB["reviews"].items():
        if r["game_id"] == gid and r["user"] == user:
            old_rating = r["rating"]
            r["rating"] = rating
            r["comment"] = comment
            r["timestamp"] = 0 
            
            g = DB["games"].get(gid)
            if g:
                g["rating_sum"] = g.get("rating_sum", 0) - old_rating + rating
                if g["rating_count"] > 0:
                    g["average_rating"] = g["rating_sum"] / g["rating_count"]
            
            atomic_save()
            return {"ok": True}

    rid = get_next_id("review")
    rev_obj = {
        "id": rid,
        "game_id": gid,
        "user": user,
        "rating": rating,
        "comment": comment,
        "timestamp": 0
    }
    DB["reviews"][rid] = rev_obj
    
    g = DB["games"].get(gid)
    if g:
        g["rating_sum"] = g.get("rating_sum", 0) + rating
        g["rating_count"] = g.get("rating_count", 0) + 1
        g["average_rating"] = g["rating_sum"] / g["rating_count"]
        
    atomic_save()
    return {"ok": True}

# --- Router ---

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    # print(f"[DB] Connection from {addr}")
    
    try:
        while True:
            req = await recvf(reader)
            # req: {collection, action, data}
            col = req.get("collection")
            act = req.get("action")
            data = req.get("data", {})
            
            resp = {"ok": False, "reason": "UNKNOWN_CMD"}
            
            async with DB_LOCK:
                if col == "Users_Dev":
                    if act == "register": resp = handle_user_dev_register(data)
                    elif act == "auth": resp = handle_user_dev_auth(data)
                    elif act == "get": 
                         u = DB["users_dev"].get(data.get("user"))
                         resp = {"ok": True, "data": u} if u else {"ok": False, "reason":"NOT_FOUND"}
                
                elif col == "Users_Player":
                    if act == "register": resp = handle_user_player_register(data)
                    elif act == "auth": resp = handle_user_player_auth(data)
                    elif act == "record_play": resp = handle_record_play(data)
                    elif act == "get":
                         u = DB["users_player"].get(data.get("user"))
                         resp = {"ok": True, "data": u} if u else {"ok": False, "reason":"NOT_FOUND"}

                elif col == "Games":
                    if act == "upload": resp = handle_game_upload(data)
                    elif act == "list": resp = handle_game_list(data)
                    elif act == "set_active": resp = handle_game_update_status(data)
                    elif act == "get":
                        g = DB["games"].get(data.get("game_id"))
                        resp = {"ok": True, "game": g} if g else {"ok": False, "reason": "NOT_FOUND"}
                
                elif col == "Reviews":
                    if act == "submit": resp = handle_submit_review(data)
                    elif act == "list":
                        gid = data.get("game_id")
                        revs = [r for r in DB["reviews"].values() if r["game_id"] == gid]
                        resp = {"ok": True, "reviews": revs}

            await sendf(writer, resp)
            
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        print(f"[DB] Error handling client: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    load_db()
    server = await asyncio.start_server(handle_client, "0.0.0.0", DB_PORT)
    print(f"[DB] Listening on 0.0.0.0:{DB_PORT}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[DB] Shutdown")
