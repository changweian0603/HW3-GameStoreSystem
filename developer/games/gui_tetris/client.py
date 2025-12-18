import asyncio
import json
import argparse
import sys
import os
import tkinter as tk
from threading import Thread
import struct

# --- Protocol ---
_MAX = 65536
def _pack(obj):
    body = json.dumps(obj).encode('utf-8')
    return struct.pack('!I', len(body)) + body

async def sendf(writer, obj):
    writer.write(_pack(obj))
    await writer.drain()

async def recvf(reader):
    raw = await reader.readexactly(4)
    n = struct.unpack('!I', raw)[0]
    data = await reader.readexactly(n)
    return json.loads(data.decode('utf-8'))

# --- Client Logic with Tkinter ---

class TetrisClientGUI:
    def __init__(self, loop, args):
        self.loop = loop
        self.args = args
        self.reader = None
        self.writer = None
        self.role = "?"
        
        self.root = tk.Tk()
        self.root.title("Tetris (GUI)")
        self.root.geometry("600x500")
        
        self.lbl_status = tk.Label(self.root, text="Connecting...", font=("Arial", 14))
        self.lbl_status.pack(pady=5)
        
        frame_boards = tk.Frame(self.root)
        frame_boards.pack(expand=True, fill="both")
        
        self.cv_p1 = tk.Canvas(frame_boards, width=200, height=400, bg="black")
        self.cv_p1.pack(side="left", padx=20)
        self.lbl_p1 = tk.Label(frame_boards, text="Player 1", font=("Arial", 12))
        self.lbl_p1.place(in_=self.cv_p1, relx=0.5, rely=-0.05, anchor="s")
        self.cv_p2 = tk.Canvas(frame_boards, width=200, height=400, bg="black")
        self.cv_p2.pack(side="right", padx=20)
        self.lbl_p2 = tk.Label(frame_boards, text="Player 2", font=("Arial", 12))
        self.lbl_p2.place(in_=self.cv_p2, relx=0.5, rely=-0.05, anchor="s")
        
        self.root.bind("<Key>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.loop.create_task(self.connect())

    def draw_board(self, canvas, rows, lines, title):
        canvas.delete("all")
        bw = 20
        
        for y, row in enumerate(rows):
            for x, char in enumerate(row):
                color = "black"
                if char == '#': color = "gray"
                elif char == '@': color = "cyan"
                
                if color != "black":
                    canvas.create_rectangle(x*bw, y*bw, (x+1)*bw, (y+1)*bw, fill=color, outline="white")
        
        canvas.create_text(10, 10, text=f"{title}\nLines: {lines}", fill="white", anchor="nw")

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.args.host, self.args.port)
            
            self.writer.write((json.dumps({"type": "AUTH", "token": self.args.token}) + "\n").encode())
            await self.writer.drain()
            
            line = await self.reader.readline()
            resp = json.loads(line.decode())
            if resp.get("status") != "OK":
                self.lbl_status.config(text=f"Auth Failed: {resp}")
                return

            self.lbl_status.config(text="Waiting for opponent...")
            
            while True:
                msg = await recvf(self.reader)
                t = msg.get("type")
                
                if t == "WELCOME":
                    self.role = msg.get("role")
                    self.root.title(f"Tetris (GUI) - You are {self.role}")
                    
                elif t == "START":
                    self.lbl_status.config(text="Game Started!")
                    
                elif t == "SNAPSHOT":
                    p1 = msg["p1"]
                    p2 = msg["p2"]
                    
                    self.draw_board(self.cv_p1, p1["board"], p1["lines"], "YOU" if self.role=="P1" else "P1")
                    self.draw_board(self.cv_p2, p2["board"], p2["lines"], "YOU" if self.role=="P2" else "P2")
                    
                elif t == "BYE":
                    reason = msg.get("reason", "")
                    self.lbl_status.config(text=f"Game Over: {reason}")
                    break
                    
        except Exception as e:
            print(f"Error: {e}")
            self.lbl_status.config(text="Connection Error")
        finally:
            self.root.quit()

    def on_key(self, event):
        if not self.writer: return 
        k = event.keysym
        action = None
        if k == 'Left': action = "L"
        elif k == 'Right': action = "R"
        elif k == 'Up': action = "CW"
        elif k == 'Down': action = "SD"
        elif k == 'space': action = "HD"
        elif k == 'z': action = "CCW"
        
        if action:
            self.loop.create_task(sendf(self.writer, {"type": "INPUT", "action": action}))

    async def on_close(self):
        try:
            if self.writer: 
                self.writer.close()
        except: pass
        
        try:
            self.root.destroy()
        except: pass
        
        os._exit(0)

    def on_close_handler(self):
        self.loop.create_task(self.on_close())

def run_gui(args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = TetrisClientGUI(loop, args)
    app.root.protocol("WM_DELETE_WINDOW", app.on_close_handler)
    
    async def tk_updater():
        while True:
            try:
                app.root.update()
                await asyncio.sleep(0.01)
            except (tk.TclError, RuntimeError):
                break
            except Exception as e:
                print(f"GUI Error: {e}")
                break
        
        try:
            tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
            for task in tasks: task.cancel()
        except: pass
        
        
        loop.stop()
        os._exit(0)
    
    try:
        loop.run_until_complete(tk_updater())
    except KeyboardInterrupt:
        pass
    os._exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    run_gui(args)
